from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CREATE = ROOT / "scripts" / "plans" / "create-implementation-notes.py"
APPEND = ROOT / "scripts" / "plans" / "append-implementation-note.py"
CONSOLIDATE = ROOT / "scripts" / "plans" / "consolidate-implementation-notes.py"
HOOK = ROOT / ".codex" / "hooks" / "implementation_notes_guard.py"


def run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None, input_text: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, input=input_text, text=True, capture_output=True, check=False)


def git(cwd: Path, *args: str) -> None:
    result = run(["git", *args], cwd=cwd)
    assert result.returncode == 0, result.stderr


def make_repo_with_worktree(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    home = tmp_path / "home"
    primary = tmp_path / "primary" / "codex-ralph-vault-loop"
    active = home / ".codex" / "worktrees" / "fixture" / "codex-ralph-vault-loop"
    primary.mkdir(parents=True)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["RALPH_PRIMARY_REPO_ROOT"] = str(primary)
    git(primary, "init")
    git(primary, "config", "user.email", "test@example.invalid")
    git(primary, "config", "user.name", "Test User")
    (primary / "README.md").write_text("# fixture\n", encoding="utf-8")
    git(primary, "add", "README.md")
    git(primary, "commit", "-m", "init")
    active.parent.mkdir(parents=True)
    git(primary, "worktree", "add", "--detach", str(active), "HEAD")
    return primary, active, env


def write_plan(path: Path, *, approved: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    status = "approved" if approved else "pending"
    path.write_text(
        "# Fixture Plan\n\n"
        "Implementation notes required: yes\n"
        "Implementation notes status: pending\n"
        f"Plan approval status: {status}\n",
        encoding="utf-8",
    )


def append_decision(notes: Path, primary: Path, active: Path, env: dict[str, str], decision: str) -> None:
    appended = run(
        [
            sys.executable,
            str(APPEND),
            "--notes",
            str(notes),
            "--category",
            "decision",
            "--decision",
            decision,
            "--reason",
            "Consolidation needs a non-initial entry.",
            "--impact",
            "The implementation index can safely learn the notes file.",
            "--primary-root",
            str(primary),
            "--active-root",
            str(active),
        ],
        cwd=ROOT,
        env=env,
    )
    assert appended.returncode == 0, appended.stderr


def stop_payload_without_plan(cwd: Path, session_id: str) -> str:
    return json.dumps(
        {
            "hook_event_name": "Stop",
            "session_id": session_id,
            "cwd": str(cwd),
            "last_assistant_message": "Implementation completed with notes.",
        }
    )


def test_stop_guard_ignores_session_state_from_other_roots(tmp_path: Path) -> None:
    primary, active, env = make_repo_with_worktree(tmp_path)
    env["CODEX_HOOK_STATE_ROOT"] = str(tmp_path / "shared-state")
    session_id = "shared-session"
    plan = primary / ".ralph" / "plans" / "stale-plan.md"
    write_plan(plan)
    state_path = Path(env["CODEX_HOOK_STATE_ROOT"]) / session_id / "implementation-notes-plan.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "session_id": session_id,
                "plan_path": str(plan),
                "implementation_notes_path": str(primary / ".ralph" / "plans" / "stale-plan-implementation-notes.html"),
                "primary_repo_root": str(tmp_path / "other-primary"),
                "active_worktree_root": str(tmp_path / "other-active"),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    guarded = run([sys.executable, str(HOOK)], cwd=ROOT, env=env, input_text=stop_payload_without_plan(active, session_id))

    assert guarded.returncode == 0, guarded.stderr
    assert guarded.stdout == ""


def test_consolidate_dry_run_finds_unindexed_current_and_legacy_notes(tmp_path: Path) -> None:
    primary, active, env = make_repo_with_worktree(tmp_path)
    current_plan = active / ".ralph" / "plans" / "current-plan.md"
    write_plan(current_plan)
    created = run(
        [sys.executable, str(CREATE), "--plan", str(current_plan), "--active-root", str(active), "--primary-root", str(primary)],
        cwd=ROOT,
        env=env,
    )
    assert created.returncode == 0, created.stderr
    current_notes = primary / ".ralph" / "plans" / "current-plan-implementation-notes.html"
    append_decision(current_notes, primary, active, env, "Keep current notes visible to consolidation.")
    (primary / ".ralph" / "plans" / "implementation-index.json").unlink()
    (primary / ".ralph" / "plans" / "implementation-index.md").unlink()

    legacy_plan = primary / ".ralph" / "plans" / "legacy-plan.md"
    write_plan(legacy_plan)
    legacy_notes = primary / ".ralph" / "plans" / "legacy-plan-implementation-notes.html"
    legacy_notes.write_text(
        "<!doctype html><html><body><h1>Implementation Notes</h1>"
        "<section><h3>Legacy decision</h3><p>Preserve legacy decisions.</p></section>"
        "</body></html>\n",
        encoding="utf-8",
    )

    result = run([sys.executable, str(CONSOLIDATE), "--active-root", str(active), "--primary-root", str(primary)], cwd=ROOT, env=env)

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["applied"] is False
    by_slug = {item["slug"]: item for item in report["records"]}
    assert by_slug["current-plan"]["schema"] == "current"
    assert by_slug["current-plan"]["actions"] == ["upsert_implementation_index"]
    assert by_slug["legacy-plan"]["schema"] == "legacy"
    assert by_slug["legacy-plan"]["actions"] == ["upsert_implementation_index"]
    assert not (primary / ".ralph" / "plans" / "implementation-index.json").exists()


def test_consolidate_apply_indexes_notes_without_touching_session_state(tmp_path: Path) -> None:
    primary, active, env = make_repo_with_worktree(tmp_path)
    env["CODEX_HOOK_STATE_ROOT"] = str(tmp_path / "shared-state")
    state_path = Path(env["CODEX_HOOK_STATE_ROOT"]) / "live-session" / "implementation-notes-plan.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_payload = {"session_id": "live-session", "plan_path": "keep-me"}
    state_path.write_text(json.dumps(state_payload, sort_keys=True) + "\n", encoding="utf-8")

    plan = active / ".ralph" / "plans" / "apply-plan.md"
    write_plan(plan)
    created = run(
        [sys.executable, str(CREATE), "--plan", str(plan), "--active-root", str(active), "--primary-root", str(primary)],
        cwd=ROOT,
        env=env,
    )
    assert created.returncode == 0, created.stderr
    notes = primary / ".ralph" / "plans" / "apply-plan-implementation-notes.html"
    append_decision(notes, primary, active, env, "Apply consolidation safely.")
    (primary / ".ralph" / "plans" / "implementation-index.json").unlink()
    (primary / ".ralph" / "plans" / "implementation-index.md").unlink()

    result = run(
        [sys.executable, str(CONSOLIDATE), "--active-root", str(active), "--primary-root", str(primary), "--apply"],
        cwd=ROOT,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    data = json.loads((primary / ".ralph" / "plans" / "implementation-index.json").read_text(encoding="utf-8"))
    assert data["plans"][0]["notes"] == ".ralph/plans/apply-plan-implementation-notes.html"
    assert data["plans"][0]["notes_schema"] == "current"
    assert state_path.read_text(encoding="utf-8") == json.dumps(state_payload, sort_keys=True) + "\n"


def test_consolidate_apply_blocks_different_worktree_copy(tmp_path: Path) -> None:
    primary, active, env = make_repo_with_worktree(tmp_path)
    plan = primary / ".ralph" / "plans" / "conflict-plan.md"
    write_plan(plan)
    primary_notes = primary / ".ralph" / "plans" / "conflict-plan-implementation-notes.html"
    primary_notes.write_text(
        "<!doctype html><html><body><h1>Implementation Notes</h1>"
        "<section><h3>Primary decision</h3><p>Primary content.</p></section></body></html>\n",
        encoding="utf-8",
    )
    active_notes = active / ".ralph" / "plans" / "conflict-plan-implementation-notes.html"
    active_notes.parent.mkdir(parents=True, exist_ok=True)
    active_notes.write_text(
        "<!doctype html><html><body><h1>Implementation Notes</h1>"
        "<section><h3>Worktree decision</h3><p>Different content.</p></section></body></html>\n",
        encoding="utf-8",
    )

    result = run(
        [sys.executable, str(CONSOLIDATE), "--active-root", str(active), "--primary-root", str(primary), "--apply"],
        cwd=ROOT,
        env=env,
    )

    assert result.returncode == 1
    assert "conflicts must be resolved" in result.stderr
    assert not (primary / ".ralph" / "plans" / "implementation-index.json").exists()
