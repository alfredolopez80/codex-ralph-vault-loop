from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "evals" / "fixtures" / "context_guard_compaction"
SCRIPT = ROOT / "scripts" / "evals" / "context_guard_autoresearch_benchmark.py"


def digest_tree(path: Path) -> dict[str, str]:
    return {
        str(item.relative_to(ROOT)): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in sorted(path.rglob("*"))
        if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc"
    }


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_context_guard_benchmark_emits_metric_and_preserves_fixture(tmp_path: Path) -> None:
    before = digest_tree(FIXTURE)
    output = tmp_path / "report.json"

    result = run_script(str(SCRIPT), "--output", str(output))

    assert result.returncode == 0, result.stderr
    assert "METRIC context_guard_acceptance_score=" in result.stdout
    assert digest_tree(FIXTURE) == before
    report = json.loads(output.read_text())
    assert report["scorecard"] == "ralph_autoresearch_v1"
    assert report["scorecard_version"] == 1
    assert report["primary_metric_present"] is True
    assert report["context_guard_acceptance_score"] >= report["decision_threshold"]
    assert report["hard_gates"]["eval_harness_unchanged"] is True
    for metric in [
        "firehose_command_block_rate",
        "bounded_command_allow_rate",
        "suggested_command_quality",
        "needle_map_script_smoke_rate",
        "compact_handoff_budget_rate",
        "compact_context",
    ]:
        assert f"METRIC {metric}=" in result.stdout
        assert report["metrics"][metric] == 1.0
    assert "data:image" not in output.read_text()


def test_context_guard_benchmark_can_omit_primary_metric_for_discard_path(tmp_path: Path) -> None:
    output = tmp_path / "missing.json"
    result = run_script(str(SCRIPT), "--output", str(output), "--simulate-missing-metric")

    assert result.returncode == 0, result.stderr
    assert "METRIC context_guard_acceptance_score=" not in result.stdout
    report = json.loads(output.read_text())
    assert report["primary_metric_present"] is False
    assert report["hard_gates"]["tests_pass"] is False


def test_context_guard_benchmark_detects_fixture_mutation(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURE, fixture)
    output = tmp_path / "mutated.json"

    result = run_script(
        str(SCRIPT),
        "--fixture",
        str(fixture),
        "--output",
        str(output),
        "--simulate-fixture-mutation",
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text())
    assert report["hard_gates"]["eval_harness_unchanged"] is False
    assert any(path.endswith(".context_guard_mutation_probe") for path in report["changed_protected_paths"])
