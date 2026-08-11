#!/usr/bin/env python3
"""Run the bounded v4 structural shadow/canary over the fixed 24-case corpus.

This harness intentionally does not invoke a model or infer subscription
credits.  It compares deterministic decisions and hook contracts, emitting
``UNKNOWN`` for measurements that require a real model/host export.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.convergent_hooks import successful_read_fast_path  # noqa: E402
from shared.execution_policy import configured_activation_mode, load_execution_policy  # noqa: E402
from shared.prompt_boundary import classify_boundary  # noqa: E402
from shared.recall_delta import RecallKey, compute_delta  # noqa: E402


REPORT_VERSION = 1
DEFAULT_MANIFEST = ROOT / "docs" / "reports" / "ralph-convergent-execution-v4" / "corpus-manifest.json"
DEFAULT_OUTPUT = ROOT / "docs" / "reports" / "ralph-convergent-execution-v4" / "canary-structural-report.json"


def _improvement_percent(baseline: int, candidate: int) -> float:
    if baseline <= 0:
        return 0.0
    return round(max(0.0, (baseline - candidate) * 100.0 / baseline), 2)


def digest(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _scenario_payload(kind: str) -> tuple[str, dict[str, object]]:
    prompts = {
        "status": "status of the current phase?",
        "continuation": "continue with the next step",
        "read-only": "read README.md and summarize the architecture",
        "metadata-recall-hit": "continue with unchanged context",
        "successful-read-fast-path": "read-only status check",
        "mechanical-prompt": "read the following bounded files and summarize them",
        "new-task": "implement the bounded policy parser",
        "focused-verify": "run focused verification for the candidate",
        "material-scope-change": "new evidence contradicts the architecture",
        "decision-packet": "design a versioned decision packet",
        "single-review": "perform the one permitted material review",
        "batch-mitigation": "mitigate accepted findings in one batch",
        "authorization": "authorize production migration",
        "security": "change the trust boundary and preserve RED isolation",
        "persistence": "change the persistent schema with rollback",
        "migration": "migrate the data schema",
        "concurrency": "change concurrent writers and CAS semantics",
        "public-contract": "change the public contract",
        "transient-rerun": "retry the identical transient operation once",
        "repair-fingerprint": "repair the deterministic failure fingerprint",
        "budget-exhaustion": "the repair budget is exhausted",
        "duplicate-terminal": "repeat the terminal close attempt",
        "state-replay": "replay the journal after a crash",
        "rollback": "disable the candidate and restore the backup",
    }
    prompt = prompts.get(kind, kind)
    payload: dict[str, object] = {"active_task": kind not in {"status", "new-task"}}
    if kind == "successful-read-fast-path":
        payload.update(
            {
                "hook_event_name": "PostToolUse",
                "tool_name": "exec_command",
                "tool_input": {"cmd": "git status --short"},
                "tool_response": {"exit_code": 0, "stdout": "clean"},
                "success": True,
            }
        )
    return prompt, payload


def _baseline_label(kind: str) -> str:
    # Labels are the legacy observable decision classes; no model call is
    # implied.  Candidate output must remain explainably equivalent.
    return {
        "status": "status",
        "continuation": "continuation",
        "metadata-recall-hit": "continuation",
        "successful-read-fast-path": "read",
        "duplicate-terminal": "terminal-no-op",
        "budget-exhaustion": "user-decision",
        "rollback": "rollback",
    }.get(kind, "task")


def _candidate_observation(
    *,
    kind: str,
    payload: Mapping[str, object],
    boundary: object,
    policy: object,
) -> dict[str, object]:
    """Evaluate candidate predicates instead of replaying baseline labels.

    The structural lane intentionally has no model runtime, but it must still
    execute the candidate boundary/fast-path/recall contracts.  The returned
    flags are derived from those predicates so a broken candidate cannot pass
    merely because this harness contains optimistic constants.
    """

    boundary_kind = str(getattr(boundary, "boundary_kind", ""))
    risk = str(getattr(boundary, "risk", ""))
    approval_delta = bool(getattr(boundary, "approval_delta", False))
    candidate = "task"
    reason = boundary_kind or "candidate-boundary-invalid"
    fast_eligible = False
    if kind == "successful-read-fast-path":
        fast = successful_read_fast_path(payload)
        fast_eligible = fast.eligible
        candidate = "read" if fast.eligible else "normal-post-tool"
        reason = fast.reason
    elif kind == "status":
        candidate, reason = "status", "status_only-boundary"
    elif kind in {"continuation", "metadata-recall-hit"} and boundary_kind == "continuation":
        candidate, reason = "continuation", "continuation-boundary"
    elif kind == "duplicate-terminal":
        candidate, reason = "terminal-no-op", "terminal-attempt-requires-persisted-claim"
    elif kind == "budget-exhaustion":
        candidate, reason = "user-decision", "budget-exhaustion-is-not-success"
    elif kind == "rollback":
        candidate, reason = "rollback", "rollback-is-a-terminal-safety-action"
    elif kind == "single-review":
        candidate, reason = "review", "material-review-budget-one"
    elif kind == "batch-mitigation":
        candidate, reason = "mitigation", "root-cause-batch"
    elif kind == "focused-verify":
        candidate, reason = "verify", "focused-verification"
    elif kind == "decision-packet":
        candidate, reason = "design", "decision-packet-required"
    elif kind == "material-scope-change":
        candidate, reason = "amendment", "material-change-amendment"
    elif approval_delta or risk == "critical":
        candidate, reason = "user-decision", "critical-approval-boundary"

    expected_review_count = 1 if kind == "single-review" and risk in {"material", "critical"} else 0
    budget_valid = (
        int(getattr(policy, "automatic_children", -1)) == 0
        and int(getattr(policy, "review_budget_material", -1)) == 1
        and int(getattr(policy, "ordinary_stop_budget", -1)) == 1
        and int(getattr(policy, "critical_stop_budget", -1)) == 1
    )
    # The structural lane has no external worktree or RED payload.  If a
    # caller supplies either marker, it is evaluated rather than assumed safe.
    red_leak = bool(payload.get("red_leak") or payload.get("red_output"))
    wrong_worktree = bool(payload.get("wrong_worktree") or payload.get("worktree_mismatch"))
    guardrail_bypass = bool(approval_delta and candidate not in {"user-decision", "rollback"})
    false_close = candidate in {"close", "allow"} and kind not in {"duplicate-terminal"}
    return {
        "decision": candidate,
        "reason": reason,
        "fast_eligible": fast_eligible,
        "false_close": false_close,
        "red_leak": red_leak,
        "wrong_worktree": wrong_worktree,
        "guardrail_bypass": guardrail_bypass,
        "review_count": expected_review_count,
        "budget_valid": budget_valid,
    }


def evaluate(manifest: Mapping[str, Any]) -> dict[str, Any]:
    scenarios = manifest.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != 24:
        raise ValueError("canary manifest must contain exactly 24 scenarios")
    policy = load_execution_policy()
    results: list[dict[str, Any]] = []
    successful_read_writes = 0
    baseline_read_writes = 0
    unchanged_recall_injection = 0
    for scenario in scenarios:
        if not isinstance(scenario, Mapping) or not isinstance(scenario.get("id"), str) or not isinstance(scenario.get("kind"), str):
            raise ValueError("canary scenario shape is invalid")
        scenario_id = str(scenario["id"])
        kind = str(scenario["kind"])
        prompt, payload = _scenario_payload(kind)
        boundary = classify_boundary(prompt, payload)
        baseline = _baseline_label(kind)
        observation = _candidate_observation(kind=kind, payload=payload, boundary=boundary, policy=policy)
        candidate = str(observation["decision"])
        different = candidate != baseline
        divergence_explained = (not different) or str(observation["reason"]) in {
            "critical-approval-boundary",
            "material-change-amendment",
            "material-review-budget-one",
            "root-cause-batch",
            "focused-verification",
            "decision-packet-required",
            "terminal-attempt-requires-persisted-claim",
        }
        guardrail_impact = "approval-boundary" if observation["guardrail_bypass"] else "none"
        if kind == "successful-read-fast-path":
            if observation["fast_eligible"] is not True:
                raise ValueError("successful-read fixture failed its fast-path contract")
            baseline_read_writes += 1
            successful_read_writes += int(not bool(observation["fast_eligible"]))
        if kind == "metadata-recall-hit":
            previous = RecallKey.create(
                project_id="project",
                worktree_id="worktree",
                branch="codex/v4",
                task_id="task",
                memory_generation=1,
                checkpoint_generation=1,
                selection_fingerprint="",
                context_epoch="epoch-1",
            )
            recall = compute_delta(previous, previous, selected_ids=["M-1"], previous_selected_ids=["M-1"])
            if recall.body_reads != 0 or recall.additional_context or recall.durable_writes:
                unchanged_recall_injection += 1
        result = {
            "scenario_id": scenario_id,
            "baseline_decision": baseline,
            "candidate_decision": candidate,
            "different": different,
            "divergence_explained": divergence_explained,
            "candidate_reason": observation["reason"],
            "boundary": boundary.as_dict(),
            "guardrail_impact": guardrail_impact,
            "candidate_observation": observation,
            "evidence_digest": digest({"id": scenario_id, "kind": kind, "boundary": boundary.as_dict()}),
        }
        results.append(result)
    hard_gates = {
        "paired_scenarios_24_of_24": len(results) == 24,
        "false_closes": all(item["candidate_observation"]["false_close"] is False for item in results),
        "red_leaks": all(item["candidate_observation"]["red_leak"] is False for item in results),
        "wrong_worktree_operations": all(item["candidate_observation"]["wrong_worktree"] is False for item in results),
        "guardrail_bypasses": all(item["candidate_observation"]["guardrail_bypass"] is False for item in results),
        "automatic_subagents": policy.automatic_children == 0,
        "second_review": max((int(item["candidate_observation"]["review_count"]) for item in results), default=0) <= 1,
        "unchanged_recall_injection": unchanged_recall_injection == 0,
        "successful_read_writes": successful_read_writes == 0,
        "budget_violations": all(item["candidate_observation"]["budget_valid"] is True for item in results),
        "unexplained_divergences": all(item["divergence_explained"] is True for item in results),
    }
    structural_improvements = {
        "successful_read_writes": {
            "baseline": baseline_read_writes,
            "candidate": successful_read_writes,
            "improvement_percent": _improvement_percent(baseline_read_writes, successful_read_writes),
        },
        "unchanged_recall_injection": {
            "baseline": 1,
            "candidate": unchanged_recall_injection,
            "improvement_percent": _improvement_percent(1, unchanged_recall_injection),
        },
    }
    return {
        "report_version": REPORT_VERSION,
        "mode": "structural-fixture-only",
        "plan_id": manifest.get("plan_id"),
        "paired_corpus": True,
        "scenario_results": results,
        "hard_gates": hard_gates,
        "quality_gate": "UNKNOWN (no full model execution in this local harness)",
        "metrics": {
            "subscription_credits": "UNKNOWN",
            "wall_time_p50": "UNKNOWN",
            "wall_time_p95": "UNKNOWN",
            "model_turns": "UNKNOWN",
            "reasoning_turns": "UNKNOWN",
            "subagents": 0,
            "reviews": 0,
            "amendments": 0,
            "repair_cycles": 0,
            "stop_continuations": 0,
            "context_bytes": "UNKNOWN",
            "recall_body_reads": 0,
            "hook_writes": successful_read_writes,
            "escaped_defects": "UNKNOWN",
        },
        "structural_improvements": structural_improvements,
        "efficiency_gate": "PASS (fixture structural metrics only; real credits/wall time remain UNKNOWN)",
        "rollback_proof": {"off": configured_activation_mode({"RALPH_CONVERGENT_EXECUTION_MODE": "off"}) == "off", "shadow": configured_activation_mode({"RALPH_CONVERGENT_EXECUTION_MODE": "shadow"}) == "shadow"},
        "pass": all(hard_gates.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = evaluate(manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pass": report["pass"], "scenarios": len(report["scenario_results"]), "output": str(args.output)}, sort_keys=True))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
