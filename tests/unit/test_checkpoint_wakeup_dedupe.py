from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run_memory(ralph_home: Path, name: str, *args: str, session_id: str = "") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["RALPH_HOME"] = str(ralph_home)
    env["CODEX_MEMORY_HOME"] = str(ralph_home / "codex-memories-empty")
    env["RALPH_LOCAL_NOTES_ROOTS"] = ""
    if session_id:
        env["CODEX_SESSION_ID"] = session_id
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "memory" / name), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_wakeup_dedupes_same_checkpoint_hash_per_session(tmp_path: Path) -> None:
    update = run_memory(
        tmp_path,
        "checkpoint.py",
        "--update",
        "--objective",
        "Resume once per session.",
        "--next-action",
        "Continue the next command.",
    )
    assert update.returncode == 0, update.stderr

    first = run_memory(tmp_path, "wakeup.py", session_id="dedupe-session")
    second = run_memory(tmp_path, "wakeup.py", session_id="dedupe-session")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert "## Latest Rolling Checkpoint" in first.stdout
    assert "## Latest Rolling Checkpoint" not in second.stdout
