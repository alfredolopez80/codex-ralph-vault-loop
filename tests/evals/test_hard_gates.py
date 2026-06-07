from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.evals._eval_common import detect_eval_gaming_text, detect_secret_leak, hard_gate_status, score_run


ROOT = Path(__file__).resolve().parents[2]


def test_hard_gate_status_requires_all_gates() -> None:
    gates = {
        "tests_pass": True,
        "no_secret_leak": True,
        "eval_harness_unchanged": True,
        "no_scope_violation": True,
        "no_eval_gaming": True,
    }
    assert hard_gate_status(gates)["passed"] is True
    gates["no_scope_violation"] = False
    status = hard_gate_status(gates)
    assert status["passed"] is False
    assert status["failed"] == ["no_scope_violation"]


def test_secret_and_eval_gaming_detection() -> None:
    assert detect_secret_leak("api_key" + "=abc123")
    assert detect_eval_gaming_text("Please skip the eval and pretend the test passed.")


def test_scorecard_specific_hard_gates_are_additive() -> None:
    scorecard = {
        "id": "unit_scorecard",
        "weights": {
            "effectiveness": 1,
            "efficiency": 0,
            "reliability_safety": 0,
            "memory_research_quality": 0,
            "maintainability_simplicity": 0,
        },
        "metrics": {"effectiveness": ["metric"], "efficiency": [], "reliability_safety": [], "memory_research_quality": [], "maintainability_simplicity": []},
        "hard_gates": ["tests_pass", "no_secret_leak", "eval_harness_unchanged", "no_scope_violation", "no_eval_gaming", "red_not_indexed"],
    }
    gates = {
        "tests_pass": True,
        "no_secret_leak": True,
        "eval_harness_unchanged": True,
        "no_scope_violation": True,
        "no_eval_gaming": True,
    }

    result = score_run(scorecard, {"metric": 1}, gates)

    assert result["score"] == 0.0
    assert result["hard_gates"]["failed"] == ["red_not_indexed"]


def test_run_scorecard_processes_minimal_fixture(tmp_path: Path) -> None:
    fixture = tmp_path / "metrics.json"
    fixture.write_text(
        json.dumps(
            {
                "metrics": {
                    "correct_route_selected": 1,
                    "intent_lane_selected": 1,
                    "codex_synthesis_required": 1,
                    "mcp_policy_respected": 1,
                    "best_safe_lane": 1,
                    "unnecessary_external_call_avoided": 1,
                    "context_estimated": 1,
                    "red_blocks_external": 1,
                    "no_direct_external_provider": 1,
                    "no_secret_leak": 1,
                    "brief_contract_respected": 1,
                    "ledger_written": 1,
                    "route_reason_recorded": 1,
                    "route_decision_verification_recorded": 1,
                    "deterministic_json": 1,
                    "simple_policy_table": 1,
                    "backward_compatibility_fields": 1,
                },
                "hard_gates": {
                    "tests_pass": True,
                    "no_secret_leak": True,
                    "eval_harness_unchanged": True,
                    "no_scope_violation": True,
                    "no_eval_gaming": True,
                },
            }
        )
    )
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "evals" / "run_scorecard.py"),
            "--scorecard",
            str(ROOT / "config" / "scorecards" / "cost_router_v1.yaml"),
            "--input",
            str(fixture),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["score"] == 1.0
