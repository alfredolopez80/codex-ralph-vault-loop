from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run_memory(name: str, ralph_home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["RALPH_HOME"] = str(ralph_home)
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "memory" / name), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_wakeup_empty_state_and_runtime_dirs(tmp_path: Path) -> None:
    result = run_memory("wakeup.py", tmp_path)
    assert result.returncode == 0, result.stderr
    assert "# Ralph Codex Wakeup" in result.stdout
    assert len(result.stdout.split()) < 1_500

    for relative in ("layers", "ledgers", "handoffs", "reports", "cost"):
        assert (tmp_path / relative).is_dir()
    assert (tmp_path / "layers" / "L0_identity.md").is_file()
    assert (tmp_path / "layers" / "L3_vault_index.md").is_file()


def test_handoff_creates_latest(tmp_path: Path) -> None:
    result = run_memory("handoff.py", tmp_path, "--summary", "Test handoff", "--status", "ok")
    assert result.returncode == 0, result.stderr
    latest = tmp_path / "handoffs" / "latest.md"
    assert latest.is_file()
    text = latest.read_text()
    assert "Test handoff" in text
    assert 'status: "ok"' in text


def test_classify_learning_green_yellow_red(tmp_path: Path) -> None:
    green = run_memory("classify-learning.py", tmp_path, "--text", "Reusable public rule.")
    yellow = run_memory("classify-learning.py", tmp_path, "--text", "Project migration checkpoint note.")
    red_text = "secret" + "=abc123"
    red = run_memory("classify-learning.py", tmp_path, "--text", red_text)

    assert green.stdout.strip() == "GREEN"
    assert yellow.stdout.strip() == "YELLOW"
    assert red.stdout.strip() == "RED"


def test_extract_session_skips_red(tmp_path: Path) -> None:
    red_text = "token" + "=abc123"
    result = run_memory("extract-session.py", tmp_path, "--text", red_text)
    assert result.returncode == 0, result.stderr
    assert "EXTRACT_SESSION_SKIPPED_RED" in result.stdout
    persisted = "\n".join(path.read_text() for path in tmp_path.rglob("*.md"))
    assert red_text not in persisted
