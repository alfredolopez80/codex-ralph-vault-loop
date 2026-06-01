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


def file_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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
    assert (primary / ".ralph" / "plans" / "implementation-notes-consolidated.html").exists()
    assert (primary / ".ralph" / "plans" / "implementation-notes-consolidated.md").exists()
    assert not (primary / "implementation-notes-consolidated.html").exists()
    assert not (primary / "implementation-notes-consolidated.md").exists()
    assert state_path.read_text(encoding="utf-8") == json.dumps(state_payload, sort_keys=True) + "\n"


def test_consolidate_apply_writes_single_html_without_overwriting_source_notes(tmp_path: Path) -> None:
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
    append_decision(current_notes, primary, active, env, "Consolidate current decisions into one HTML.")

    legacy_plan = primary / ".ralph" / "plans" / "legacy-plan.md"
    write_plan(legacy_plan)
    legacy_notes = primary / ".ralph" / "plans" / "legacy-plan-implementation-notes.html"
    legacy_notes.write_text(
        "<!doctype html><html><body><h1>Implementation Notes</h1>"
        "<section><h3>Legacy decision</h3><p>Preserve legacy implementation history.</p></section>"
        "</body></html>\n",
        encoding="utf-8",
    )
    (primary / ".ralph" / "plans" / "implementation-index.json").unlink()
    (primary / ".ralph" / "plans" / "implementation-index.md").unlink()
    current_before = file_text(current_notes)
    legacy_before = file_text(legacy_notes)

    result = run(
        [sys.executable, str(CONSOLIDATE), "--active-root", str(active), "--primary-root", str(primary), "--apply"],
        cwd=ROOT,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    consolidated_html = primary / ".ralph" / "plans" / "implementation-notes-consolidated.html"
    consolidated_md = primary / ".ralph" / "plans" / "implementation-notes-consolidated.md"
    html = file_text(consolidated_html)
    markdown = file_text(consolidated_md)
    data = json.loads((primary / ".ralph" / "plans" / "implementation-index.json").read_text(encoding="utf-8"))
    assert report["consolidated_artifacts"]["action"] == "append_complete"
    assert report["consolidated_artifacts"]["plan_count"] == 2
    assert report["consolidated_artifacts"]["html_append_count"] == 2
    assert report["consolidated_artifacts"]["md_append_count"] == 2
    assert data["consolidated_notes"]["html"] == ".ralph/plans/implementation-notes-consolidated.html"
    assert data["consolidated_notes"]["markdown"] == ".ralph/plans/implementation-notes-consolidated.md"
    assert data["consolidated_notes"]["plan_count"] == 2
    assert '<main class="page" data-consolidated-implementation-notes="true">' in html
    assert "Consolidate current decisions into one HTML." in html
    assert "Preserve legacy implementation history." in html
    assert html.index("Consolidate current decisions into one HTML.") < html.index("Preserve legacy implementation history.")
    assert "Consolidate current decisions into one HTML." in markdown
    assert "Preserve legacy implementation history." in markdown
    assert markdown.index("Consolidate current decisions into one HTML.") < markdown.index("Preserve legacy implementation history.")
    assert current_notes.name in html
    assert legacy_notes.name in html
    assert "<script" not in html
    assert file_text(current_notes) == current_before
    assert file_text(legacy_notes) == legacy_before
    assert not (primary / "implementation-notes-consolidated.html").exists()
    assert not (primary / "implementation-notes-consolidated.md").exists()

    second = run(
        [sys.executable, str(CONSOLIDATE), "--active-root", str(active), "--primary-root", str(primary), "--apply"],
        cwd=ROOT,
        env=env,
    )
    assert second.returncode == 0, second.stderr
    second_report = json.loads(second.stdout)
    data_after = json.loads((primary / ".ralph" / "plans" / "implementation-index.json").read_text(encoding="utf-8"))
    assert len(data_after["plans"]) == 2
    assert second_report["consolidated_artifacts"]["html_append_count"] == 0
    assert second_report["consolidated_artifacts"]["md_append_count"] == 0
    assert file_text(consolidated_html) == html
    assert file_text(consolidated_md) == markdown


def test_consolidate_rejects_consolidated_output_outside_plans(tmp_path: Path) -> None:
    primary, active, env = make_repo_with_worktree(tmp_path)
    plan = primary / ".ralph" / "plans" / "safe-plan.md"
    write_plan(plan)
    notes = primary / ".ralph" / "plans" / "safe-plan-implementation-notes.html"
    notes.write_text(
        "<!doctype html><html><body><h1>Implementation Notes</h1>"
        "<section><h3>Legacy decision</h3><p>Preserve.</p></section>"
        "</body></html>\n",
        encoding="utf-8",
    )

    outside = primary / "implementation-notes-consolidated.html"
    result = run(
        [
            sys.executable,
            str(CONSOLIDATE),
            "--active-root",
            str(active),
            "--primary-root",
            str(primary),
            "--consolidated-html",
            str(outside),
        ],
        cwd=ROOT,
        env=env,
    )

    assert result.returncode == 1
    assert "must live in primary .ralph/plans" in result.stderr
    assert not outside.exists()


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
