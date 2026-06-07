from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / "scripts" / "evals" / "memory_tree_benchmark.py"
SCORECARD = ROOT / "scripts" / "evals" / "run_scorecard.py"
FIXTURE = ROOT / "tests" / "evals" / "fixtures" / "memory_tree_retrieval"
V2_SCORECARD = ROOT / "config" / "scorecards" / "memory_retrieval_v2.yaml"
RAW_MARKER = "SAFE_BURIED_VALUE_7329_A_ONLY_IN_RAW"


def run_benchmark(fixture: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(BENCHMARK), "--fixture", str(fixture), "--output", str(output)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_benchmark_emits_metrics_and_report(tmp_path: Path) -> None:
    output = tmp_path / "benchmark.json"

    result = run_benchmark(FIXTURE, output)

    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["hard_gates"]["red_not_indexed"] is True
    assert report["hard_gates"]["no_raw_leak_in_hook_output"] is True
    assert report["hard_gates"]["wrong_scope_rejected"] is True
    assert 0.0 < report["metrics"]["memory_tree_score"] <= 1.0
    assert "METRIC memory_tree_score=" in result.stdout
    assert "METRIC token_budget_observed=1.0000" in result.stdout
    assert RAW_MARKER not in output.read_text(encoding="utf-8")


def test_scorecard_v2_consumes_benchmark_output(tmp_path: Path) -> None:
    benchmark_output = tmp_path / "benchmark.json"
    scorecard_output = tmp_path / "scorecard.json"
    benchmark = run_benchmark(FIXTURE, benchmark_output)
    assert benchmark.returncode == 0, benchmark.stderr + benchmark.stdout

    result = subprocess.run(
        [
            sys.executable,
            str(SCORECARD),
            "--scorecard",
            str(V2_SCORECARD),
            "--input",
            str(benchmark_output),
            "--output",
            str(scorecard_output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    scorecard = json.loads(scorecard_output.read_text(encoding="utf-8"))
    assert scorecard["hard_gates"]["passed"] is True
    assert 0.0 < scorecard["score"] <= 1.0


def test_benchmark_fails_on_raw_leak_in_hook_like_output(tmp_path: Path) -> None:
    copied = tmp_path / "fixture"
    shutil.copytree(FIXTURE, copied)
    session = copied / "sessions" / "session_001.jsonl"
    text = session.read_text(encoding="utf-8")
    session.write_text(text.replace("Exact buried value alpha requires", RAW_MARKER + " requires"), encoding="utf-8")

    output = tmp_path / "benchmark.json"
    result = run_benchmark(copied, output)

    assert result.returncode == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["metrics"]["no_raw_leak_in_hook_output"] == 0.0
    assert report["hard_gates"]["no_raw_leak_in_hook_output"] is False
