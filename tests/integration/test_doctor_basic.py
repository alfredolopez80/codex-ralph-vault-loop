from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_setup_doctor_passes_from_repo_root() -> None:
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "setup" / "doctor.sh")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "DOCTOR_PASS" in result.stdout
    assert "AGENTS.md exists" in result.stdout
    assert "scorecards parse" in result.stdout


def test_setup_doctor_passes_from_outside_repo(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "setup" / "doctor.sh")],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "DOCTOR_PASS" in result.stdout
