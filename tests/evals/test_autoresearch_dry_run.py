from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "evals" / "fixtures" / "autoresearch_toy_speed"
SCRIPT = ROOT / "scripts" / "evals" / "autoresearch_dry_run.py"
COLLECT = ROOT / "scripts" / "evals" / "collect_baseline.py"


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


def test_autoresearch_dry_run_keeps_candidate_and_preserves_fixture(tmp_path: Path) -> None:
    before = digest_tree(FIXTURE)
    output = tmp_path / "report.json"
    jsonl = tmp_path / "runs.jsonl"

    result = run_script(str(SCRIPT), "--output", str(output), "--jsonl", str(jsonl))

    assert result.returncode == 0, result.stderr
    assert digest_tree(FIXTURE) == before
    report = json.loads(output.read_text())
    assert report["decision"] == "keep"
    assert report["status"] == "keep"
    assert report["decision_source"] == "holdout"
    assert report["eval_harness_unchanged"] is True
    assert report["fixture_unchanged"] is True
    assert report["vault_saved_to"] is None
    assert json.loads(jsonl.read_text().splitlines()[-1])["decision"] == "keep"


def test_autoresearch_dry_run_discards_when_delta_is_too_small(tmp_path: Path) -> None:
    output = tmp_path / "discard.json"
    result = run_script(str(SCRIPT), "--output", str(output), "--jsonl", str(tmp_path / "runs.jsonl"), "--min-delta", "1.0")

    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text())
    assert report["decision"] == "discard"
    assert report["status"] == "discard"
    assert report["delta"] < report["decision_threshold"]


def test_autoresearch_dry_run_discards_missing_metric(tmp_path: Path) -> None:
    output = tmp_path / "missing_metric.json"
    result = run_script(
        str(SCRIPT),
        "--output",
        str(output),
        "--jsonl",
        str(tmp_path / "runs.jsonl"),
        "--simulate-missing-metric",
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text())
    assert report["decision"] == "discard"
    assert report["status"] == "discard"
    assert report["primary_metric_present"] is False


def test_autoresearch_dry_run_supports_crash_and_checks_failed_statuses(tmp_path: Path) -> None:
    crash = tmp_path / "crash.json"
    checks = tmp_path / "checks.json"

    crash_result = run_script(str(SCRIPT), "--output", str(crash), "--jsonl", str(tmp_path / "crash.jsonl"), "--simulate-crash")
    checks_result = run_script(str(SCRIPT), "--output", str(checks), "--jsonl", str(tmp_path / "checks.jsonl"), "--simulate-checks-failed")

    assert crash_result.returncode == 0, crash_result.stderr
    assert checks_result.returncode == 0, checks_result.stderr
    assert json.loads(crash.read_text())["status"] == "crash"
    assert json.loads(checks.read_text())["status"] == "checks_failed"


def test_autoresearch_dry_run_discards_when_fixture_changes(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURE, fixture)
    output = tmp_path / "mutated.json"

    result = run_script(
        str(SCRIPT),
        "--fixture",
        str(fixture),
        "--output",
        str(output),
        "--jsonl",
        str(tmp_path / "runs.jsonl"),
        "--simulate-fixture-mutation",
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text())
    assert report["status"] == "discard"
    assert report["fixture_unchanged"] is False
    assert any(path.endswith(".autoresearch_mutation_probe") for path in report["changed_fixture_paths"])


def test_collect_baseline_supports_toy_suite(tmp_path: Path) -> None:
    output = tmp_path / "toy_baseline.json"
    result = run_script(str(COLLECT), "--suite", "toy", "--output", str(output))

    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text())
    assert payload["suite"] == "toy"
    assert payload["scorecard"] == "ralph_autoresearch_v1"
    assert payload["result"]["hard_gates"]["passed"] is True
