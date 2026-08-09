from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / "scripts" / "evals" / "hook_runtime_cost_benchmark.py"

SCENARIOS = {
    "small_read_only",
    "small_edit",
    "medium_edit_test",
    "repeated_prompt",
    "session_start_startup",
    "session_start_compact",
    "stop_allow",
    "stop_objective_failure",
    "subagent_route",
    "red_safety",
}
PROFILES = {"luna", "sol", "conservative_unknown"}


def load_benchmark():
    spec = importlib.util.spec_from_file_location("hook_runtime_cost_benchmark_test", BENCHMARK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hook_runtime_cost_benchmark_emits_real_scenario_profile_matrix(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["RALPH_HOOK_COST_ITERATIONS"] = "1"
    env["RALPH_HOOK_COST_WARMUP"] = "0"
    env["RALPH_HOME"] = str(tmp_path / "must-not-be-used")
    env["CODEX_MEMORY_HOME"] = str(tmp_path / "must-not-be-used-memory")
    env["VAULT_DIR"] = str(tmp_path / "must-not-be-used-vault")
    env["RALPH_LOCAL_NOTES_ROOTS"] = ""

    result = subprocess.run(
        [sys.executable, str(BENCHMARK)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    json_text, metric_text = result.stdout.split("\nMETRIC ", 1)
    report = json.loads(json_text)
    assert report["schema_version"] == 2
    assert report["iterations"] == 1
    assert report["warmup_iterations"] == 0
    assert report["subscription_usage_measured"] is False
    assert report["configured_handlers_by_event"] == {
        "PostToolUse": 1,
        "PreToolUse": 1,
        "SessionStart": 1,
        "Stop": 1,
        "SubagentStart": 1,
        "SubagentStop": 1,
        "UserPromptSubmit": 1,
    }

    matrix = report["scenario_matrix"]
    assert len(matrix) == len(SCENARIOS) * len(PROFILES)
    assert {case["scenario"] for case in matrix} == SCENARIOS
    assert {case["profile"] for case in matrix} == PROFILES
    assert {(case["scenario"], case["profile"]) for case in matrix} == {
        (scenario, profile) for scenario in SCENARIOS for profile in PROFILES
    }
    required_case_fields = {
        "event",
        "role",
        "scenario",
        "profile",
        "model_family",
        "tool_family",
        "configured_handler_count",
        "matched_handler_count",
        "executed_handler_count",
        "process_count",
        "child_process_count",
        "child_process_count_measured",
        "skipped_reason",
        "components_considered",
        "components_executed",
        "components_skipped",
        "runtime_wall_ms",
        "runtime_p50_ms",
        "runtime_p95_ms",
        "output_bytes",
        "estimated_context_units",
        "block_count",
        "continuation_count",
        "persisted_bytes_delta",
        "cache_hits",
        "advisor_count",
        "subscription_usage_measured",
    }
    assert all(required_case_fields <= set(case) for case in matrix)
    assert all(case["subscription_usage_measured"] is False for case in matrix)
    assert all(case["executed_handler_count"] <= case["matched_handler_count"] for case in matrix)
    assert all(case["process_count"] == case["executed_handler_count"] for case in matrix)
    assert report["source_scopes_measured"] == ["project", "global", "suppressed-global"]
    assert len(report["scope_cases"]) == 14
    assert {case["source_scope"] for case in report["scope_cases"]} == {"global", "suppressed-global"}
    assert all(
        case["matched_handler_count"] == 0 and case["executed_handler_count"] == 0 and case["output_bytes"] == 0
        for case in report["scope_cases"]
        if case["source_scope"] == "suppressed-global"
    )

    prompt_cases = [case for case in matrix if case["scenario"] == "repeated_prompt"]
    assert all(case["configured_handler_count"] == 1 for case in prompt_cases)
    assert all(case["executed_handler_count"] == 2 for case in prompt_cases)
    assert all(case["cache_hits"] == 1 for case in prompt_cases)
    assert next(case for case in prompt_cases if case["profile"] == "luna")["output_bytes_max"] <= 1_800
    assert next(case for case in prompt_cases if case["profile"] == "sol")["output_bytes_max"] <= 800

    red_cases = [case for case in matrix if case["scenario"] == "red_safety"]
    assert all(case["block_count"] == 1 for case in red_cases)
    assert all(case["continuation_count"] == 0 for case in red_cases)
    assert all(case["child_process_count"] == 0 for case in red_cases)
    assert report["successful_post_tool_stdout_chars"] == 0
    assert report["successful_stop_stdout_chars"] == 0
    assert "METRIC hook_cost_score=" in result.stdout
    assert "METRIC hook_total_p50_ms=" in result.stdout
    assert "METRIC hook_output_context_units=" in result.stdout
    assert metric_text.startswith("hook_cost_score=")

    rendered = json.dumps(report, sort_keys=True).lower()
    assert "fixture-secret-value" not in rendered
    assert "review the effective hook pipeline" not in rendered
    assert str(tmp_path).lower() not in rendered


def test_matcher_counts_are_derived_from_configuration(tmp_path: Path) -> None:
    module = load_benchmark()
    config = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "apply_patch|Edit|Write", "hooks": [{"command": "one"}, {"command": "two"}]},
                {"matcher": "Agent|spawn_agent", "hooks": [{"command": "three"}]},
            ]
        }
    }
    path = tmp_path / "hooks.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    loaded = module.load_hook_config(path)
    assert module.configured_handler_counts(loaded)["PreToolUse"] == 3
    assert module.matched_handlers(loaded, "PreToolUse", {"tool_name": "Edit"}) == 2
    assert module.matched_handlers(loaded, "PreToolUse", {"tool_name": "spawn_agent"}) == 1
    assert module.matched_handlers(loaded, "PreToolUse", {"tool_name": "Read"}) == 0


def test_malformed_matcher_fails_loudly() -> None:
    module = load_benchmark()
    config = {"hooks": {"PreToolUse": [{"matcher": "[", "hooks": [{"command": "one"}]}]}}
    try:
        module.matched_handlers(config, "PreToolUse", {"tool_name": "Edit"})
    except ValueError as exc:
        assert "invalid matcher" in str(exc)
    else:  # pragma: no cover - explicit regression signal
        raise AssertionError("malformed matcher was silently treated as zero matches")


def test_percentile_never_turns_missing_samples_into_zero() -> None:
    module = load_benchmark()
    assert module.percentile([1.0, 2.0, 3.0, 4.0, 100.0], 95) == 100.0
    try:
        module.percentile([], 95)
    except ValueError as exc:
        assert "samples" in str(exc)
    else:  # pragma: no cover - explicit regression signal
        raise AssertionError("missing samples were silently reported as zero")
