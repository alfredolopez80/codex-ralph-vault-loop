from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DISPATCHER = ROOT / ".codex" / "hooks" / "global_hook_dispatch.py"
CLI = ROOT / "scripts" / "plans" / "progress.py"


def _git(root: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def _run(command: list[str], payload: dict[str, object], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def test_installed_dispatcher_updates_and_completes_canonical_progress(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Dispatcher Test")
    plan = repo / ".ralph" / "plans" / "dispatcher.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Dispatcher plan\nPlan approval status: approved\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")

    env = os.environ.copy()
    env.update(
        {
            "RALPH_PROGRESS_PRIMARY_ROOT": str(repo),
            "RALPH_HOME": str(tmp_path / "ralph"),
            "CODEX_MEMORY_HOME": str(tmp_path / "memory"),
            "VAULT_DIR": str(tmp_path / "vault"),
            "RALPH_LOCAL_NOTES_ROOTS": "",
            "CODEX_HOOK_STATE_ROOT": str(tmp_path / "hook-state"),
            "CODEX_SLOP_GUARD_ENABLED": "0",
            "CODEX_SESSION_ID": "dispatcher-session",
        }
    )
    started = subprocess.run(
        ["python3", str(CLI), "start", "--plan", str(plan), "--format", "json"],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert started.returncode == 0, started.stderr

    base = {
        "cwd": str(repo),
        "primary_repo_root": str(repo),
        "session_id": "dispatcher-session",
        "tool_use_id": "dispatcher-tool",
        "tool_name": "exec_command",
        "tool_input": {"cmd": "pytest -q"},
        "tool_response": {"exit_code": 0, "stdout": "1 passed"},
        "success": True,
        "model": "gpt-5.6-luna",
    }
    post = _run(
        ["python3", str(DISPATCHER), "--event", "PostToolUse", "--role", "post_tool_dispatch"],
        {"hook_event_name": "PostToolUse", **base},
        cwd=repo,
        env=env,
    )
    assert post.returncode == 0, post.stderr
    assert post.stdout == ""
    state_path = repo / ".local-notes" / "ralph" / "implementation" / "plans" / "dispatcher" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["validation"] == {"tests": "pass"}

    stop = _run(
        ["python3", str(DISPATCHER), "--event", "Stop", "--role", "stop_dispatch"],
        {
            "hook_event_name": "Stop",
            "cwd": str(repo),
            "primary_repo_root": str(repo),
            "session_id": "dispatcher-session",
            "task_signature": "dispatcher-task",
            "progress_plan_id": "dispatcher",
            "progress_complete": True,
            "validation_status": "pass",
        },
        cwd=repo,
        env=env,
    )
    assert stop.returncode == 0, stop.stderr
    assert stop.stdout == ""
    final_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert final_state["status"] == "completed"
    assert len(list((repo / ".local-notes" / "ralph" / "implementation").rglob("*.md"))) == 0
    assert len(list((repo / ".local-notes" / "ralph" / "implementation").rglob("*.html"))) == 0
