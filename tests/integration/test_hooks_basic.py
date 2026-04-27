from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"


def run_hook(name: str, ralph_home: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["RALPH_HOME"] = str(ralph_home)
    return subprocess.run(
        [sys.executable, str(HOOKS / name)],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_hooks_accept_empty_json(tmp_path: Path) -> None:
    for hook in [
        "session_start_wakeup.py",
        "user_prompt_capture.py",
        "pre_tool_guard.py",
        "post_tool_extract_memory.py",
        "post_tool_cost_ledger.py",
        "stop_persist_memory.py",
    ]:
        result = run_hook(hook, tmp_path, {})
        assert result.returncode == 0, f"{hook}: {result.stderr}"


def test_pre_tool_guard_blocks_destructive_command(tmp_path: Path) -> None:
    result = run_hook("pre_tool_guard.py", tmp_path, {"tool_input": {"command": "git reset --hard HEAD"}})
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert "git reset" not in payload["reason"]


def test_post_tool_hooks_write_ledgers(tmp_path: Path) -> None:
    memory = run_hook(
        "post_tool_extract_memory.py",
        tmp_path,
        {"output": "Validated checkpoint PASS after fixing root cause."},
    )
    assert memory.returncode == 0, memory.stderr
    assert list((tmp_path / "ledgers").glob("learning-*.md"))

    cost = run_hook("post_tool_cost_ledger.py", tmp_path, {"tool_name": "exec_command", "success": True})
    assert cost.returncode == 0, cost.stderr
    assert (tmp_path / "cost" / "tool-ledger.jsonl").is_file()


def test_stop_hook_creates_handoff_without_red(tmp_path: Path) -> None:
    result = run_hook(
        "stop_persist_memory.py",
        tmp_path,
        {"last_assistant_message": "Implemented deterministic hook persistence."},
    )
    assert result.returncode == 0, result.stderr
    latest = tmp_path / "handoffs" / "latest.md"
    assert latest.is_file()
    assert "deterministic hook persistence" in latest.read_text()

    red_text = "secret" + "=abc123"
    run_hook("stop_persist_memory.py", tmp_path, {"last_assistant_message": red_text})
    assert red_text not in latest.read_text()
