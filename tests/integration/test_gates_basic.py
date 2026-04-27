from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run_gate(*args: str, report_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GATES_REPORT_DIR"] = str(report_dir)
    env["RALPH_GATES_SKIP_TEST_EXECUTION"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gates" / "run-gates.py"), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_run_gates_minimal_generates_reports(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    result = run_gate("--minimal", report_dir=report_dir)
    assert result.returncode == 0, result.stderr

    latest_json = report_dir / "latest.json"
    latest_md = report_dir / "latest.md"
    assert latest_json.is_file()
    assert latest_md.is_file()

    report = json.loads(latest_json.read_text())
    assert report["mode"] == "minimal"
    assert report["summary"]["status"] == "passed"
    assert report["results"]
    assert all(item["status"] in {"passed", "failed", "skipped"} for item in report["results"])


def test_detect_project_outputs_real_capabilities() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gates" / "detect-project.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["python"]["present"] is True
    assert "security" in data


def test_security_minimal_skips_without_failure() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gates" / "run-security.py"), "--mode", "minimal"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["results"][0]["status"] == "skipped"
