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


def test_checkpoint_rejects_invalid_schema_status(tmp_path: Path) -> None:
    result = run_checkpoint(
        tmp_path,
        "--update",
        "--objective",
        "Invalid status should fail schema validation.",
        "--next-action",
        "Do not write checkpoint.",
        "--status",
        "paused",
    )

    assert result.returncode == 2
    assert "status must be one of" in result.stderr
    assert not (tmp_path / "checkpoints" / "latest.json").exists()
