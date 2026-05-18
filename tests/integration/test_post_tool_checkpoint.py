from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".codex" / "hooks" / "post_tool_checkpoint.py"


def run_hook(ralph_home: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["RALPH_HOME"] = str(ralph_home)
    env["CODEX_MEMORY_HOME"] = str(ralph_home / "codex-memories-empty")
    env["RALPH_LOCAL_NOTES_ROOTS"] = ""
    return subprocess.run(
        [sys.executable, str(HOOK)],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def latest_json(root: Path) -> dict:
    matches = sorted(root.glob("projects/*/checkpoints/latest.json"))
    assert len(matches) == 1
    return json.loads(matches[0].read_text(encoding="utf-8"))


def all_text(root: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in root.rglob("*") if path.is_file())


def test_post_tool_checkpoint_records_passing_test_summary(tmp_path: Path) -> None:
    result = run_hook(
        tmp_path,
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "functions.exec_command",
            "success": True,
            "tool_input": {"command": "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_checkpoint_basic.py"},
            "output": "long raw output that should not be persisted",
        },
    )

    assert result.returncode == 0, result.stderr
    checkpoint = latest_json(tmp_path)
    assert checkpoint["source"] == "PostToolUse"
    assert checkpoint["validation_status"] == "pass"
    assert checkpoint["commands_run"][0]["result"] == "pass"
    assert "pytest tests/unit/test_checkpoint_basic.py" in checkpoint["last_verified_state"]
    assert "long raw output" not in all_text(tmp_path)


def test_post_tool_checkpoint_records_failure_blocker(tmp_path: Path) -> None:
    result = run_hook(
        tmp_path,
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "functions.exec_command",
            "success": False,
            "tool_input": {"command": "make test"},
            "output_preview": "1 failed",
        },
    )

    assert result.returncode == 0, result.stderr
    checkpoint = latest_json(tmp_path)
    assert checkpoint["validation_status"] == "fail"
    assert checkpoint["commands_run"][0]["result"] == "fail"
    assert checkpoint["blockers"] == ["Command failed: make test"]


def test_post_tool_checkpoint_records_touched_files(tmp_path: Path) -> None:
    result = run_hook(
        tmp_path,
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "functions.apply_patch",
            "success": True,
            "tool_input": {"path": "scripts/memory/wakeup.py"},
        },
    )

    assert result.returncode == 0, result.stderr
    checkpoint = latest_json(tmp_path)
    assert checkpoint["active_files"] == ["scripts/memory/wakeup.py"]
    assert checkpoint["last_verified_state"] == "Tracked file changes for current task."


def test_post_tool_checkpoint_skips_red_output_without_leak(tmp_path: Path) -> None:
    red_text = "token" + "=abc123"
    result = run_hook(
        tmp_path,
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "functions.exec_command",
            "success": True,
            "tool_input": {"command": "python3 scripts/example.py"},
            "output_preview": red_text,
        },
    )

    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.glob("projects/*/checkpoints/latest.json"))
    assert red_text not in all_text(tmp_path)
    assert "abc123" not in all_text(tmp_path)
