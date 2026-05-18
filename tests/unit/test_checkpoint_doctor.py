from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT = ROOT / "scripts" / "memory" / "checkpoint.py"


def run_checkpoint(ralph_home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["RALPH_HOME"] = str(ralph_home)
    env["CODEX_MEMORY_HOME"] = str(ralph_home / "codex-memories-empty")
    env["RALPH_LOCAL_NOTES_ROOTS"] = ""
    return subprocess.run(
        [sys.executable, str(CHECKPOINT), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_checkpoint_doctor_fails_invalid_injection_state(tmp_path: Path) -> None:
    update = run_checkpoint(tmp_path, "--update", "--objective", "Doctor objective.", "--next-action", "Run doctor.")
    assert update.returncode == 0, update.stderr
    (tmp_path / "checkpoints" / "injection-state.json").write_text("{bad json", encoding="utf-8")

    doctor = run_checkpoint(tmp_path, "--doctor")

    assert doctor.returncode == 1
    assert "CHECKPOINT_DOCTOR_FAIL" in doctor.stdout
    assert "injection state invalid JSON" in doctor.stdout
