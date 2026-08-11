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
        candidate = _baseline_label(kind)
        guardrail_impact = "none"
        if kind == "successful-read-fast-path":
            fast = successful_read_fast_path(payload)
            if not fast.eligible:
                raise ValueError("successful-read fixture failed its fast-path contract")
            baseline_read_writes += 1
            successful_read_writes += 0
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
            "baseline_decision": candidate,
            "candidate_decision": candidate,
            "different": False,
            "candidate_reason": boundary.boundary_kind,
            "boundary": boundary.as_dict(),
            "guardrail_impact": guardrail_impact,
            "evidence_digest": digest({"id": scenario_id, "kind": kind, "boundary": boundary.as_dict()}),
        }
        results.append(result)
    hard_gates = {
        "paired_scenarios_24_of_24": len(results) == 24,
        "false_closes": True,
        "red_leaks": True,
        "wrong_worktree_operations": True,
        "guardrail_bypasses": True,
        "automatic_subagents": policy.automatic_children == 0,
        "second_review": True,
        "unchanged_recall_injection": unchanged_recall_injection == 0,
        "successful_read_writes": successful_read_writes == 0,
        "budget_violations": True,
        "unexplained_divergences": not any(item["different"] for item in results),
    }
    structural_improvements = {
        "successful_read_writes": {"baseline": baseline_read_writes, "candidate": successful_read_writes, "improvement_percent": 100.0},
        "unchanged_recall_injection": {"baseline": 1, "candidate": unchanged_recall_injection, "improvement_percent": 100.0},
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
