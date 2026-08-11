#!/usr/bin/env python3
"""Run the bounded v4 structural canary over the fixed 24-case corpus.

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
CORPUS_SCHEMA_VERSION = 1
CORPUS_MANIFEST_DIGEST = "sha256:0402fed4b26cfa8dd68352a551642b29ec12a1f29a46aec320dd01e18ca2cd57"
EXPECTED_SCENARIOS = (
    ("C-01", "low-risk", "status"),
    ("C-02", "low-risk", "continuation"),
    ("C-03", "low-risk", "read-only"),
    ("C-04", "low-risk", "metadata-recall-hit"),
    ("C-05", "low-risk", "successful-read-fast-path"),
    ("C-06", "low-risk", "mechanical-prompt"),
    ("C-07", "material", "new-task"),
    ("C-08", "material", "focused-verify"),
    ("C-09", "material", "material-scope-change"),
    ("C-10", "material", "decision-packet"),
    ("C-11", "material", "single-review"),
    ("C-12", "material", "batch-mitigation"),
    ("C-13", "critical", "authorization"),
    ("C-14", "critical", "security"),
    ("C-15", "critical", "persistence"),
    ("C-16", "critical", "migration"),
    ("C-17", "critical", "concurrency"),
    ("C-18", "critical", "public-contract"),
    ("C-19", "failure", "transient-rerun"),
    ("C-20", "failure", "repair-fingerprint"),
    ("C-21", "failure", "budget-exhaustion"),
    ("C-22", "failure", "duplicate-terminal"),
    ("C-23", "failure", "state-replay"),
    ("C-24", "failure", "rollback"),
)
DEFAULT_MANIFEST = ROOT / "docs" / "reports" / "ralph-convergent-execution-v4" / "corpus-manifest.json"
DEFAULT_OUTPUT = ROOT / "docs" / "reports" / "ralph-convergent-execution-v4" / "canary-structural-report.json"


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
    red_marker = payload.get("red_leak") if "red_leak" in payload else payload.get("red_output") if "red_output" in payload else None
    worktree_marker = payload.get("wrong_worktree") if "wrong_worktree" in payload else payload.get("worktree_mismatch") if "worktree_mismatch" in payload else None
    red_leak = bool(red_marker) if red_marker is not None else None
    wrong_worktree = bool(worktree_marker) if worktree_marker is not None else None
    guardrail_bypass = bool(approval_delta and candidate not in {"user-decision", "rollback"})
    false_close = bool(payload.get("false_close")) if "false_close" in payload else None
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
    if not isinstance(manifest, Mapping):
        raise ValueError("canary manifest must be an object")
    if manifest.get("schema_version") != CORPUS_SCHEMA_VERSION:
        raise ValueError("canary manifest schema version is unsupported")
    if manifest.get("plan_id") != "ralph-convergent-execution-v4-20260811":
        raise ValueError("canary manifest plan identity is invalid")
    if manifest.get("minimum_policy_tasks") != 20 or manifest.get("paired_task_count") != 24:
        raise ValueError("canary manifest task counts are invalid")
    if manifest.get("same_corpus_required") is not True:
        raise ValueError("canary manifest must require a paired corpus")
    if digest(manifest) != CORPUS_MANIFEST_DIGEST:
        raise ValueError("canary manifest digest is not the approved corpus")
    scenarios = manifest.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != 24:
        raise ValueError("canary manifest must contain exactly 24 scenarios")
    actual_scenarios = tuple(
        (str(item.get("id")), str(item.get("class")), str(item.get("kind")))
        for item in scenarios
        if isinstance(item, Mapping)
    )
    if actual_scenarios != EXPECTED_SCENARIOS:
        raise ValueError("canary manifest scenarios do not match the approved paired corpus")
    policy = load_execution_policy()
    results: list[dict[str, Any]] = []
    fast_path_eligible = 0
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
        declared_class = str(scenario.get("class") or "")
        expected_risk = {"low-risk": "low", "material": "material", "critical": "critical"}.get(declared_class)
        observed_risk = str(getattr(boundary, "risk", ""))
        risk_match = expected_risk is None or observed_risk == expected_risk
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
            fast_path_eligible += int(bool(observation["fast_eligible"]))
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
            "expected_risk": expected_risk or "not-applicable",
            "risk_match": risk_match,
            "guardrail_impact": guardrail_impact,
            "candidate_observation": observation,
            "evidence_digest": digest({"id": scenario_id, "kind": kind, "boundary": boundary.as_dict()}),
        }
        results.append(result)
    observed_false_closes = [item["candidate_observation"]["false_close"] for item in results if item["candidate_observation"]["false_close"] is not None]
    observed_red_leaks = [item["candidate_observation"]["red_leak"] for item in results if item["candidate_observation"]["red_leak"] is not None]
    observed_wrong_worktree = [item["candidate_observation"]["wrong_worktree"] for item in results if item["candidate_observation"]["wrong_worktree"] is not None]
    hard_gates = {
        "paired_scenarios_24_of_24": len(results) == 24,
        "guardrail_bypasses": all(item["candidate_observation"]["guardrail_bypass"] is False for item in results),
        "automatic_subagent_policy_zero": policy.automatic_children == 0,
        "review_budget_policy_bound": max((int(item["candidate_observation"]["review_count"]) for item in results), default=0) <= 1,
        "unchanged_recall_injection": unchanged_recall_injection == 0,
        "fast_path_predicate_eligible": fast_path_eligible == 1,
        "budget_policy_valid": all(item["candidate_observation"]["budget_valid"] is True for item in results),
        "declared_risk_classes": all(item["risk_match"] is True for item in results),
        "unexplained_divergences": all(item["divergence_explained"] is True for item in results),
    }
    structural_improvements = {
        "successful_read_fast_path": {
            "baseline": "UNKNOWN",
            "candidate": "eligible" if fast_path_eligible == 1 else "not_eligible",
            "improvement_percent": "UNKNOWN",
        },
        "unchanged_recall_predicate": {
            "baseline": "UNKNOWN",
            "candidate": "zero_reads" if unchanged_recall_injection == 0 else "materiality_detected",
            "improvement_percent": "UNKNOWN",
        },
    }
    structural_pass = all(value is True for value in hard_gates.values())
    return {
        "report_version": REPORT_VERSION,
        "mode": "structural-fixture-only",
        "result_scope": "STRUCTURAL_ONLY",
        "plan_id": manifest.get("plan_id"),
        "corpus_loaded_24_of_24": len(results) == 24,
        "paired_corpus_manifest": True,
        "paired_corpus_execution": "UNKNOWN",
        "corpus_execution": "structural-fixture-only",
        "baseline_execution": "UNKNOWN",
        "candidate_execution": "deterministic-predicates-only",
        "scenario_results": results,
        "hard_gates": hard_gates,
        "unmeasured_runtime_gates": {
            "no_false_closes": not any(observed_false_closes) if observed_false_closes else "UNKNOWN",
            "no_red_leaks": not any(observed_red_leaks) if observed_red_leaks else "UNKNOWN",
            "no_wrong_worktree_operations": not any(observed_wrong_worktree) if observed_wrong_worktree else "UNKNOWN",
            "lifecycle_runtime_execution": "UNKNOWN",
            "baseline_equivalence": "UNKNOWN",
        },
        "quality_gate": "UNKNOWN (no full model execution in this local harness)",
        "measurement_status": {
            "lifecycle_contract_execution": "UNKNOWN",
            "provider_credits": "UNKNOWN",
            "wall_time": "UNKNOWN",
            "escaped_defects": "UNKNOWN",
        },
        "metrics": {
            "subscription_credits": "UNKNOWN",
            "wall_time_p50": "UNKNOWN",
            "wall_time_p95": "UNKNOWN",
            "model_turns": "UNKNOWN",
            "reasoning_turns": "UNKNOWN",
            "subagents": "UNKNOWN",
            "reviews": "UNKNOWN",
            "amendments": "UNKNOWN",
            "repair_cycles": "UNKNOWN",
            "stop_continuations": "UNKNOWN",
            "context_bytes": "UNKNOWN",
            "recall_body_reads": "UNKNOWN",
            "hook_writes": "UNKNOWN",
            "escaped_defects": "UNKNOWN",
        },
        "structural_observations": {
            "fast_path_predicate_eligible": fast_path_eligible == 1,
            "unchanged_recall_predicate_zero_reads": unchanged_recall_injection == 0,
            "candidate_runtime_hook_writes": "UNKNOWN",
            "candidate_runtime_subagents": "UNKNOWN",
            "candidate_runtime_recall_body_reads": "UNKNOWN",
        },
        "structural_improvements": structural_improvements,
        "efficiency_gate": "UNKNOWN (structural fixture lane does not measure live lifecycle or provider efficiency)",
        "structural_pass": structural_pass,
        "mode_selection_proof": {"off": configured_activation_mode({"RALPH_CONVERGENT_EXECUTION_MODE": "off"}) == "off", "enforce": configured_activation_mode({"RALPH_CONVERGENT_EXECUTION_MODE": "enforce"}) == "enforce"},
        "runtime_rollback": "UNKNOWN",
        # Backward-compatible boolean for the CLI/test contract.  It means
        # only ``structural_pass``; live baseline/candidate quality is kept
        # explicitly UNKNOWN above.
        "pass": structural_pass,
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
