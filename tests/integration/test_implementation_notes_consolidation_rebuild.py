from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATE = ROOT / "scripts" / "plans" / "consolidate-implementation-notes.py"


def run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, check=False)


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


def write_plan(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Fixture Plan\n\n"
        "Implementation notes required: yes\n"
        "Implementation notes status: pending\n"
        "Plan approval status: approved\n",
        encoding="utf-8",
    )


def write_legacy_notes(path: Path, body: str) -> None:
    path.write_text(
        "<!doctype html><html><body><h1>Implementation Notes</h1>"
        f"<section><h3>Legacy decision</h3><p>{body}</p></section>"
        "</body></html>\n",
        encoding="utf-8",
    )


def remove_generated_index(primary: Path) -> None:
    (primary / ".ralph" / "plans" / "implementation-index.json").unlink(missing_ok=True)
    (primary / ".ralph" / "plans" / "implementation-index.md").unlink(missing_ok=True)


def file_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_consolidate_apply_rebuild_rewrites_existing_consolidated_artifacts(tmp_path: Path) -> None:
    primary, active, env = make_repo_with_worktree(tmp_path)
    old_plan = primary / ".ralph" / "plans" / "old-plan.md"
    old_notes = primary / ".ralph" / "plans" / "old-plan-implementation-notes.html"
    write_plan(old_plan)
    write_legacy_notes(old_notes, "Old content should not survive rebuild.")
    remove_generated_index(primary)
    first = run(
        [sys.executable, str(CONSOLIDATE), "--active-root", str(active), "--primary-root", str(primary), "--apply"],
        cwd=ROOT,
        env=env,
    )
    assert first.returncode == 0, first.stderr

    old_notes.unlink()
    old_plan.unlink()
    new_plan = primary / ".ralph" / "plans" / "new-plan.md"
    new_notes = primary / ".ralph" / "plans" / "new-plan-implementation-notes.html"
    write_plan(new_plan)
    write_legacy_notes(new_notes, "New content replaces old consolidated output.")

    rebuilt = run(
        [sys.executable, str(CONSOLIDATE), "--active-root", str(active), "--primary-root", str(primary), "--apply", "--rebuild"],
        cwd=ROOT,
        env=env,
    )

    assert rebuilt.returncode == 0, rebuilt.stderr
    report = json.loads(rebuilt.stdout)
    consolidated_html = primary / ".ralph" / "plans" / "implementation-notes-consolidated.html"
    consolidated_md = primary / ".ralph" / "plans" / "implementation-notes-consolidated.md"
    html = file_text(consolidated_html)
    markdown = file_text(consolidated_md)
    data = json.loads((primary / ".ralph" / "plans" / "implementation-index.json").read_text(encoding="utf-8"))
    assert report["consolidated_artifacts"]["action"] == "rebuild_complete"
    assert report["consolidated_artifacts"]["html_append_count"] == 1
    assert report["consolidated_artifacts"]["md_append_count"] == 1
    assert data["consolidated_notes"]["last_operation"] == "rebuild"
    assert "New content replaces old consolidated output." in html
    assert "New content replaces old consolidated output." in markdown
    assert "Old content should not survive rebuild." not in html
    assert "Old content should not survive rebuild." not in markdown


def test_consolidate_legacy_notes_keep_full_text_without_character_limit(tmp_path: Path) -> None:
    primary, active, env = make_repo_with_worktree(tmp_path)
    plan = primary / ".ralph" / "plans" / "full-legacy-plan.md"
    notes = primary / ".ralph" / "plans" / "full-legacy-plan-implementation-notes.html"
    long_legacy_text = "A" * 7000 + "TAIL_MARKER_FULL_TEXT"
    write_plan(plan)
    write_legacy_notes(notes, long_legacy_text)
    remove_generated_index(primary)

    result = run(
        [sys.executable, str(CONSOLIDATE), "--active-root", str(active), "--primary-root", str(primary), "--apply"],
        cwd=ROOT,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    consolidated_html = primary / ".ralph" / "plans" / "implementation-notes-consolidated.html"
    consolidated_md = primary / ".ralph" / "plans" / "implementation-notes-consolidated.md"
    html = file_text(consolidated_html)
    markdown = file_text(consolidated_md)
    assert "Legacy text" in html
    assert "Show full legacy text" in html
    assert "Excerpt" not in html
    assert "TAIL_MARKER_FULL_TEXT" in html
    assert "TAIL\\_MARKER\\_FULL\\_TEXT" in markdown
    assert len(html) > 7000
