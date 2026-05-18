from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".codex" / "hooks" / "continuity_prompt_context.py"


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


def latest_checkpoint(root: Path) -> dict:
    matches = sorted(root.glob("projects/*/checkpoints/latest.json"))
    assert len(matches) == 1
    return json.loads(matches[0].read_text(encoding="utf-8"))


def test_continuity_prompt_accepts_empty_json(tmp_path: Path) -> None:
    result = run_hook(tmp_path, {})

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_continuity_prompt_updates_objective_and_injects_once(tmp_path: Path) -> None:
    new_task = run_hook(
        tmp_path,
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "fixture-continuity",
            "prompt": "Implement the rolling checkpoint continuation hook.",
        },
    )
    assert new_task.returncode == 0, new_task.stderr
    assert new_task.stdout == ""
    checkpoint = latest_checkpoint(tmp_path)
    assert checkpoint["objective"] == "Implement the rolling checkpoint continuation hook."
    assert checkpoint["next_action"] == "Continue the user's latest requested task."

    continuation = run_hook(
        tmp_path,
        {"hook_event_name": "UserPromptSubmit", "session_id": "fixture-continuity", "prompt": "continua"},
    )
    assert continuation.returncode == 0, continuation.stderr
    payload = json.loads(continuation.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert "Latest rolling checkpoint:" in context
    assert "Objective: Implement the rolling checkpoint continuation hook." in context

    duplicate = run_hook(
        tmp_path,
        {"hook_event_name": "UserPromptSubmit", "session_id": "fixture-continuity", "prompt": "continua"},
    )
    assert duplicate.returncode == 0, duplicate.stderr
    assert duplicate.stdout == ""


def test_continuity_prompt_does_not_inject_unrelated_or_red_prompt(tmp_path: Path) -> None:
    unrelated = run_hook(
        tmp_path,
        {"hook_event_name": "UserPromptSubmit", "session_id": "fixture-unrelated", "prompt": "Explain this repo briefly."},
    )
    assert unrelated.returncode == 0, unrelated.stderr
    assert unrelated.stdout == ""

    red_text = "token" + "=abc123"
    red = run_hook(
        tmp_path,
        {"hook_event_name": "UserPromptSubmit", "session_id": "fixture-red", "prompt": red_text},
    )
    assert red.returncode == 0, red.stderr
    assert red.stdout == ""
    persisted = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in tmp_path.rglob("*") if path.is_file())
    assert red_text not in persisted
    assert "abc123" not in persisted
