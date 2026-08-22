from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "scripts" / "gates" / "runtime_optimization_gate.py"


def load_gate():
    spec = importlib.util.spec_from_file_location("runtime_optimization_gate_test", GATE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_current_candidate_passes_structural_gate() -> None:
    gate = load_gate()
    report = gate.inspect(ROOT)
    assert report["status"] == "passed", report
    assert report["profile"] == "security-only"
    assert report["handler_counts"]["SessionStart"] == 0
    assert report["handler_counts"]["UserPromptSubmit"] == 0
    assert report["handler_counts"]["PreToolUse"] == 1
    assert report["handler_counts"]["PostToolUse"] == 0
    assert report["handler_counts"]["Stop"] == 0
    assert report["context_hard_caps"] == {
        "conservative_unknown_prompt": 2200,
        "conservative_unknown_session": 2200,
        "luna_prompt": 1800,
        "luna_session": 2200,
        "sol_prompt": 800,
        "sol_session": 800,
    }


def test_handler_increase_is_a_hard_failure(tmp_path: Path) -> None:
    gate = load_gate()
    baseline = {"handler_counts": {"PostToolUse": 1}, "errors": []}
    candidate = {"handler_counts": {"PostToolUse": 2}, "errors": []}
    result = gate.compare(baseline, candidate)
    assert result["status"] == "failed"
    assert "handler_count_increased:PostToolUse" in result["errors"]


def test_missing_universal_invariant_is_rejected(tmp_path: Path) -> None:
    gate = load_gate()
    agents = tmp_path / "AGENTS.md"
    agents.write_text("Codex main decides. External models advise. evidence. Implementation notes.\n", encoding="utf-8")
    codex = tmp_path / ".codex"
    codex.mkdir()
    (codex / "hooks.json").write_text(json.dumps({"hooks": {}}), encoding="utf-8")
    (codex / "config.toml").write_text("[agents]\nmax_threads=2\nmax_depth=1\n", encoding="utf-8")
    result = gate.inspect(tmp_path)
    marker = "R" + "ED"
    assert f"missing_invariant:{marker}" in result["errors"]


def test_instruction_size_limit_is_enforced(tmp_path: Path) -> None:
    gate = load_gate()
    (tmp_path / "AGENTS.md").write_bytes(b"x" * (14 * 1024 + 1))
    codex = tmp_path / ".codex"
    codex.mkdir()
    (codex / "hooks.json").write_text(json.dumps({"hooks": {}}), encoding="utf-8")
    (codex / "config.toml").write_text("[agents]\nmax_threads=2\nmax_depth=1\n", encoding="utf-8")
    result = gate.inspect(tmp_path)
    assert "agents_instruction_hard_cap" in result["errors"]


def _benchmark_case(runtime_p95_ms: float) -> dict[str, object]:
    return {
        "event": "Stop",
        "role": "stop_dispatch",
        "scenario": "stop_allow",
        "effective_config": "project",
        "source_scope": "project",
        "runtime_p95_ms": runtime_p95_ms,
    }


def test_benchmark_regression_is_a_hard_failure(tmp_path: Path) -> None:
    gate = load_gate()
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    baseline.write_text(json.dumps({"schema_version": 2, "subscription_usage_measured": False, "cases": [_benchmark_case(100.0)]}), encoding="utf-8")
    candidate.write_text(json.dumps({"schema_version": 2, "subscription_usage_measured": False, "cases": [_benchmark_case(120.0)]}), encoding="utf-8")
    result = gate.compare_benchmark_reports(baseline, candidate, 0.05)
    assert result["classification"] == "regresión"


def test_incompatible_benchmark_is_explicit(tmp_path: Path) -> None:
    gate = load_gate()
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    baseline.write_text(json.dumps({"cases": []}), encoding="utf-8")
    candidate.write_text(json.dumps({"schema_version": 2, "subscription_usage_measured": False, "cases": [_benchmark_case(100.0)]}), encoding="utf-8")
    result = gate.compare_benchmark_reports(baseline, candidate, 0.05)
    assert result["classification"] == "cambio no comparable"
    assert "schema_version" in result["error"]


def _scenario_case(scenario: str, profile: str, *, output_bytes: int = 0) -> dict[str, object]:
    family = "unknown" if profile == "conservative_unknown" else profile
    if scenario == "repeated_prompt":
        event = "UserPromptSubmit"
        role = "user_prompt_dispatch"
    elif scenario.startswith("session_start_"):
        event = "SessionStart"
        role = "session_start_dispatch"
    elif scenario.startswith("stop_"):
        event = "Stop"
        role = "stop_dispatch"
    elif scenario in {"small_read_only", "small_edit", "medium_edit_test"}:
        event = "PreToolUse+PostToolUse"
        role = "pre_tool_dispatch+post_tool_dispatch"
    else:
        event = "PreToolUse"
        role = "pre_tool_dispatch"
    blocks = 1 if scenario in {"stop_objective_failure", "red_safety"} else 0
    return {
        "event": event,
        "role": role,
        "scenario": scenario,
        "profile": profile,
        "model_family": family,
        "effective_config": "project_only",
        "source_scope": "project",
        "configured_handler_count": 1,
        "matched_handler_count": 1,
        "executed_handler_count": 1,
        "process_count": 1,
        "child_process_count": 0,
        "child_process_count_measured": True,
        "output_bytes": output_bytes,
        "output_bytes_max": output_bytes,
        "estimated_context_units": (output_bytes + 3) // 4,
        "persisted_bytes_delta": 0,
        "block_count": blocks,
        "continuation_count": 1 if scenario == "stop_objective_failure" else 0,
        "advisor_count": 0,
        "cache_hits": 0,
        "subscription_usage_measured": False,
    }


def _matrix_report() -> dict[str, object]:
    scenarios = {
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
    profiles = {"luna", "sol", "conservative_unknown"}
    matrix = [
        _scenario_case(scenario, profile, output_bytes=800 if scenario == "repeated_prompt" and profile == "sol" else 0)
        for scenario in sorted(scenarios)
        for profile in sorted(profiles)
    ]
    return {
        "schema_version": 2,
        "subscription_usage_measured": False,
        "configured_handlers_by_event": {
            "SessionStart": 1,
            "UserPromptSubmit": 1,
            "PreToolUse": 1,
            "PostToolUse": 1,
            "SubagentStart": 1,
            "SubagentStop": 1,
            "Stop": 1,
        },
        "scenario_matrix": matrix,
        "cases": matrix,
        "successful_post_tool_stdout_chars": 0,
        "successful_stop_stdout_chars": 0,
    }


def test_benchmark_hard_gate_requires_full_matrix_and_profile_caps() -> None:
    gate = load_gate()
    report = _matrix_report()
    assert gate.benchmark_hard_errors(report) == []

    report["scenario_matrix"] = list(report["scenario_matrix"])[1:]
    assert "benchmark_matrix_incomplete" in gate.benchmark_hard_errors(report)

    report = _matrix_report()
    sol = next(
        case
        for case in report["scenario_matrix"]
        if case["scenario"] == "repeated_prompt" and case["profile"] == "sol"
    )
    sol["output_bytes_max"] = 801
    assert "benchmark_context_cap:sol" in gate.benchmark_hard_errors(report)


def test_benchmark_hard_gate_rejects_handler_drift_and_subscription_claim() -> None:
    gate = load_gate()
    report = _matrix_report()
    report["configured_handlers_by_event"]["PreToolUse"] = 2
    report["subscription_usage_measured"] = True
    errors = gate.benchmark_hard_errors(report)
    assert "benchmark_handler_target:PreToolUse" in errors
    assert "benchmark_subscription_usage_claim" in errors


def test_runtime_regression_is_a_soft_warning_not_a_flaky_structural_failure(tmp_path: Path) -> None:
    gate = load_gate()
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    baseline.write_text(json.dumps({"schema_version": 2, "subscription_usage_measured": False, "cases": [_benchmark_case(100.0)]}), encoding="utf-8")
    candidate.write_text(json.dumps({"schema_version": 2, "subscription_usage_measured": False, "cases": [_benchmark_case(120.0)]}), encoding="utf-8")
    comparison = gate.compare_benchmark_reports(baseline, candidate, 0.05)
    assert gate.benchmark_performance_warnings(comparison) == ["benchmark_regression"]
