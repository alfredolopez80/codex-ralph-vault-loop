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
    assert report["handler_counts"]["PostToolUse"] == 1
    assert report["handler_counts"]["Stop"] == 1


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
