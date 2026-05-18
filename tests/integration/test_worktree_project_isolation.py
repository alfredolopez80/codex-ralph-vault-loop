from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTINUITY = ROOT / ".codex" / "hooks" / "continuity_prompt_context.py"
USER_PROMPT = ROOT / ".codex" / "hooks" / "user_prompt_capture.py"
STOP = ROOT / ".codex" / "hooks" / "stop_persist_memory.py"
SESSION_START = ROOT / ".codex" / "hooks" / "session_start_wakeup.py"


def init_git(path: Path, remote: str | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, stdout=subprocess.DEVNULL)
    if remote:
        subprocess.run(["git", "remote", "add", "origin", remote], cwd=path, check=True)


def env_for(ralph_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["RALPH_HOME"] = str(ralph_home)
    env["CODEX_MEMORY_HOME"] = str(ralph_home / "codex-memory-empty")
    env["RALPH_LOCAL_NOTES_ROOTS"] = ""
    return env


def run_hook(script: Path, ralph_home: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env_for(ralph_home),
        check=False,
    )


def latest_checkpoints(ralph_home: Path) -> list[Path]:
    return sorted(ralph_home.glob("projects/*/checkpoints/latest.json"))


def test_continuation_checkpoint_is_project_scoped(tmp_path: Path) -> None:
    ralph_home = tmp_path / "ralph"
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    init_git(project_a)
    init_git(project_b)

    created = run_hook(
        CONTINUITY,
        ralph_home,
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "session-a",
            "cwd": str(project_a),
            "prompt": "Implement project A scoped rolling checkpoint behavior.",
        },
    )
    assert created.returncode == 0, created.stderr
    assert created.stdout == ""
    checkpoints = latest_checkpoints(ralph_home)
    assert len(checkpoints) == 1
    checkpoint_a = json.loads(checkpoints[0].read_text(encoding="utf-8"))
    assert checkpoint_a["project"] == "project-a"
    assert checkpoint_a["project_id"]

    wrong_project = run_hook(
        CONTINUITY,
        ralph_home,
        {"hook_event_name": "UserPromptSubmit", "session_id": "session-b", "cwd": str(project_b), "prompt": "continua"},
    )
    assert wrong_project.returncode == 0, wrong_project.stderr
    assert wrong_project.stdout == ""

    same_project = run_hook(
        CONTINUITY,
        ralph_home,
        {"hook_event_name": "UserPromptSubmit", "session_id": "session-a", "cwd": str(project_a), "prompt": "continua"},
    )
    assert same_project.returncode == 0, same_project.stderr
    payload = json.loads(same_project.stdout)
    assert "Implement project A scoped rolling checkpoint behavior." in payload["hookSpecificOutput"]["additionalContext"]


def test_continuation_checkpoint_is_session_scoped_within_same_project(tmp_path: Path) -> None:
    ralph_home = tmp_path / "ralph"
    project = tmp_path / "shared-project"
    init_git(project)

    created = run_hook(
        CONTINUITY,
        ralph_home,
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "session-a",
            "cwd": str(project),
            "prompt": "Implement session scoped checkpoint behavior.",
        },
    )
    assert created.returncode == 0, created.stderr

    other_session = run_hook(
        CONTINUITY,
        ralph_home,
        {"hook_event_name": "UserPromptSubmit", "session_id": "session-b", "cwd": str(project), "prompt": "continua"},
    )
    assert other_session.returncode == 0, other_session.stderr
    assert other_session.stdout == ""

    same_session = run_hook(
        CONTINUITY,
        ralph_home,
        {"hook_event_name": "UserPromptSubmit", "session_id": "session-a", "cwd": str(project), "prompt": "continua"},
    )
    assert same_session.returncode == 0, same_session.stderr
    payload = json.loads(same_session.stdout)
    assert "Implement session scoped checkpoint behavior." in payload["hookSpecificOutput"]["additionalContext"]


def test_continuation_checkpoint_is_workspace_scoped_for_same_remote_project(tmp_path: Path) -> None:
    ralph_home = tmp_path / "ralph"
    remote = "git@example.com:org/shared.git"
    worktree_a = tmp_path / "worktree-a"
    worktree_b = tmp_path / "worktree-b"
    init_git(worktree_a, remote)
    init_git(worktree_b, remote)

    created = run_hook(
        CONTINUITY,
        ralph_home,
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "same-session",
            "cwd": str(worktree_a),
            "prompt": "Implement workspace scoped checkpoint behavior.",
        },
    )
    assert created.returncode == 0, created.stderr
    checkpoint = json.loads(latest_checkpoints(ralph_home)[0].read_text(encoding="utf-8"))
    assert checkpoint["project_id"]

    other_workspace = run_hook(
        CONTINUITY,
        ralph_home,
        {"hook_event_name": "UserPromptSubmit", "session_id": "same-session", "cwd": str(worktree_b), "prompt": "continua"},
    )

    assert other_workspace.returncode == 0, other_workspace.stderr
    assert other_workspace.stdout == ""

    wakeup_other_workspace = run_hook(
        SESSION_START,
        ralph_home,
        {"hook_event_name": "SessionStart", "session_id": "same-session", "cwd": str(worktree_b)},
    )
    assert wakeup_other_workspace.returncode == 0, wakeup_other_workspace.stderr
    assert "## Latest Rolling Checkpoint" not in wakeup_other_workspace.stdout
    assert "Implement workspace scoped checkpoint behavior." not in wakeup_other_workspace.stdout

    wakeup_source_workspace = run_hook(
        SESSION_START,
        ralph_home,
        {"hook_event_name": "SessionStart", "session_id": "same-session", "cwd": str(worktree_a)},
    )
    assert wakeup_source_workspace.returncode == 0, wakeup_source_workspace.stderr
    assert "## Latest Rolling Checkpoint" in wakeup_source_workspace.stdout
    assert "Implement workspace scoped checkpoint behavior." in wakeup_source_workspace.stdout


def test_session_start_handoff_is_workspace_scoped_for_same_remote_project(tmp_path: Path) -> None:
    ralph_home = tmp_path / "ralph"
    remote = "git@example.com:org/shared.git"
    worktree_a = tmp_path / "worktree-a"
    worktree_b = tmp_path / "worktree-b"
    marker = "same remote handoff must stay in source workspace"
    init_git(worktree_a, remote)
    init_git(worktree_b, remote)

    stopped = run_hook(
        STOP,
        ralph_home,
        {"hook_event_name": "Stop", "session_id": "same-session", "cwd": str(worktree_a), "last_assistant_message": marker},
    )
    assert stopped.returncode == 0, stopped.stderr
    handoffs = sorted(ralph_home.glob("projects/*/handoffs/latest.md"))
    assert len(handoffs) == 1
    assert marker in handoffs[0].read_text(encoding="utf-8")
    project_runtime = handoffs[0].parents[1]
    scheduler_state = project_runtime / "reports" / "memory" / "dream-scheduler.json"
    scheduler_state.parent.mkdir(parents=True, exist_ok=True)
    scheduler_state.write_text(
        json.dumps(
            {
                "last_success_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "last_processed_learning_event_count": 0,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    other_workspace = run_hook(
        SESSION_START,
        ralph_home,
        {"hook_event_name": "SessionStart", "session_id": "same-session", "cwd": str(worktree_b)},
    )

    assert other_workspace.returncode == 0, other_workspace.stderr
    assert marker not in other_workspace.stdout
    assert "## Latest Handoff" not in other_workspace.stdout

    source_workspace = run_hook(
        SESSION_START,
        ralph_home,
        {"hook_event_name": "SessionStart", "session_id": "same-session", "cwd": str(worktree_a)},
    )

    assert source_workspace.returncode == 0, source_workspace.stderr
    assert "## Latest Handoff" in source_workspace.stdout
    assert marker in source_workspace.stdout


def test_user_prompt_capture_uses_active_project_and_hash_only_prompt_ledger(tmp_path: Path) -> None:
    ralph_home = tmp_path / "ralph"
    project = tmp_path / "project-b"
    init_git(project)
    prompt = "Implement worktree aware recall for project B without leaking prompt text."

    result = run_hook(
        USER_PROMPT,
        ralph_home,
        {"hook_event_name": "UserPromptSubmit", "session_id": "session-b", "cwd": str(project), "prompt": prompt},
    )

    assert result.returncode == 0, result.stderr
    assert "PROJECT_SLUG=project-b" in result.stdout
    ledgers = sorted(ralph_home.glob("projects/*/ledgers/user-prompts.jsonl"))
    assert len(ledgers) == 1
    text = ledgers[0].read_text(encoding="utf-8")
    payload = json.loads(text.splitlines()[-1])
    assert payload["project"] == "project-b"
    assert payload["prompt_hash"]
    assert "prompt" not in payload
    assert prompt not in text
