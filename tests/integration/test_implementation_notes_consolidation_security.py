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


def run(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, check=False)


def git(cwd: Path, *args: str) -> None:
    result = run(["git", *args], cwd=cwd, env=os.environ.copy())
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


def append_decision(notes: Path, primary: Path, active: Path, env: dict[str, str]) -> None:
    result = run(
        [
            sys.executable,
            str(APPEND),
            "--notes",
            str(notes),
            "--category",
            "decision",
            "--decision",
            "Keep current notes safe during consolidation.",
            "--reason",
            "The file needs one non-initial entry.",
            "--impact",
            "The fixture can exercise current-schema scanning.",
            "--primary-root",
            str(primary),
            "--active-root",
            str(active),
        ],
        cwd=ROOT,
        env=env,
    )
    assert result.returncode == 0, result.stderr


def test_consolidate_apply_blocks_unsafe_legacy_html(tmp_path: Path) -> None:
    primary, active, env = make_repo_with_worktree(tmp_path)
    plan = primary / ".ralph" / "plans" / "unsafe-legacy-plan.md"
    write_plan(plan)
    notes = primary / ".ralph" / "plans" / "unsafe-legacy-plan-implementation-notes.html"
    notes.write_text(
        "<!doctype html><html><body><h1>Implementation Notes</h1>"
        "<section><h3>Legacy decision</h3><p onclick=\"steal()\">Preserve as text.</p></section>"
        "<script>alert('unsafe')</script>"
        "</body></html>\n",
        encoding="utf-8",
    )

    result = run(
        [sys.executable, str(CONSOLIDATE), "--active-root", str(active), "--primary-root", str(primary), "--apply"],
        cwd=ROOT,
        env=env,
    )

    assert result.returncode == 1
    report = json.loads(result.stdout)
    by_slug = {item["slug"]: item for item in report["records"]}
    assert by_slug["unsafe-legacy-plan"]["schema"] == "invalid"
    assert "unsafe implementation notes HTML is not allowed" in by_slug["unsafe-legacy-plan"]["schema_error"]
    assert "conflicts must be resolved" in result.stderr
    assert not (primary / ".ralph" / "plans" / "implementation-index.json").exists()
    assert not (primary / ".ralph" / "plans" / "implementation-notes-consolidated.html").exists()
    assert not (primary / ".ralph" / "plans" / "implementation-notes-consolidated.md").exists()


def test_consolidate_apply_blocks_meta_refresh_html(tmp_path: Path) -> None:
    primary, active, env = make_repo_with_worktree(tmp_path)
    plan = primary / ".ralph" / "plans" / "meta-refresh-plan.md"
    write_plan(plan)
    notes = primary / ".ralph" / "plans" / "meta-refresh-plan-implementation-notes.html"
    notes.write_text(
        "<!doctype html><html><head><meta http-equiv=\"refresh\" content=\"0;url=https://example.invalid\"></head>"
        "<body><h1>Implementation Notes</h1><section><h3>Legacy decision</h3><p>Preserve.</p></section>"
        "</body></html>\n",
        encoding="utf-8",
    )

    result = run(
        [sys.executable, str(CONSOLIDATE), "--active-root", str(active), "--primary-root", str(primary), "--apply"],
        cwd=ROOT,
        env=env,
    )

    assert result.returncode == 1
    report = json.loads(result.stdout)
    by_slug = {item["slug"]: item for item in report["records"]}
    assert by_slug["meta-refresh-plan"]["schema"] == "invalid"
    assert "unsafe implementation notes HTML is not allowed" in by_slug["meta-refresh-plan"]["schema_error"]
    assert not (primary / ".ralph" / "plans" / "implementation-notes-consolidated.html").exists()


def test_consolidate_apply_validates_consolidated_targets_before_index_mutation(tmp_path: Path) -> None:
    primary, active, env = make_repo_with_worktree(tmp_path)
    plan = active / ".ralph" / "plans" / "preflight-plan.md"
    write_plan(plan)
    created = run(
        [sys.executable, str(CREATE), "--plan", str(plan), "--active-root", str(active), "--primary-root", str(primary)],
        cwd=ROOT,
        env=env,
    )
    assert created.returncode == 0, created.stderr
    notes = primary / ".ralph" / "plans" / "preflight-plan-implementation-notes.html"
    append_decision(notes, primary, active, env)
    (primary / ".ralph" / "plans" / "implementation-index.json").unlink()
    (primary / ".ralph" / "plans" / "implementation-index.md").unlink()
    corrupt_md = primary / ".ralph" / "plans" / "implementation-notes-consolidated.md"
    corrupt_md.write_text("# Missing append anchor\n", encoding="utf-8")

    result = run(
        [sys.executable, str(CONSOLIDATE), "--active-root", str(active), "--primary-root", str(primary), "--apply"],
        cwd=ROOT,
        env=env,
    )

    assert result.returncode == 1
    assert "Markdown append anchor not found" in result.stderr
    assert not (primary / ".ralph" / "plans" / "implementation-index.json").exists()
    assert not (primary / ".ralph" / "plans" / "implementation-notes-consolidated.html").exists()


def test_consolidate_apply_blocks_worktree_notes_symlink_escape(tmp_path: Path) -> None:
    primary, active, env = make_repo_with_worktree(tmp_path)
    plan = active / ".ralph" / "plans" / "symlink-source-plan.md"
    write_plan(plan)
    created = run(
        [sys.executable, str(CREATE), "--plan", str(plan), "--active-root", str(active), "--primary-root", str(primary)],
        cwd=ROOT,
        env=env,
    )
    assert created.returncode == 0, created.stderr
    primary_notes = primary / ".ralph" / "plans" / "symlink-source-plan-implementation-notes.html"
    append_decision(primary_notes, primary, active, env)
    outside_notes = tmp_path / "outside-notes.html"
    outside_notes.write_text(primary_notes.read_text(encoding="utf-8"), encoding="utf-8")
    primary_notes.unlink()
    active_notes = active / ".ralph" / "plans" / "symlink-source-plan-implementation-notes.html"
    active_notes.parent.mkdir(parents=True, exist_ok=True)
    active_notes.symlink_to(outside_notes)
    (primary / ".ralph" / "plans" / "implementation-index.json").unlink()
    (primary / ".ralph" / "plans" / "implementation-index.md").unlink()

    result = run(
        [sys.executable, str(CONSOLIDATE), "--active-root", str(active), "--primary-root", str(primary), "--apply"],
        cwd=ROOT,
        env=env,
    )

    assert result.returncode == 1
    report = json.loads(result.stdout)
    by_slug = {item["slug"]: item for item in report["records"]}
    assert "symlink target escapes .ralph/plans" in " ".join(by_slug["symlink-source-plan"]["conflicts"])
    assert "conflicts must be resolved" in result.stderr
    assert not primary_notes.exists()
    assert not (primary / ".ralph" / "plans" / "implementation-index.json").exists()
    assert not (primary / ".ralph" / "plans" / "implementation-notes-consolidated.html").exists()
    assert not (primary / ".ralph" / "plans" / "implementation-notes-consolidated.md").exists()


def test_consolidate_apply_blocks_unsafe_current_schema_worktree_html(tmp_path: Path) -> None:
    primary, active, env = make_repo_with_worktree(tmp_path)
    plan = active / ".ralph" / "plans" / "unsafe-current-plan.md"
    write_plan(plan)
    created = run(
        [sys.executable, str(CREATE), "--plan", str(plan), "--active-root", str(active), "--primary-root", str(primary)],
        cwd=ROOT,
        env=env,
    )
    assert created.returncode == 0, created.stderr
    primary_notes = primary / ".ralph" / "plans" / "unsafe-current-plan-implementation-notes.html"
    append_decision(primary_notes, primary, active, env)
    active_notes = active / ".ralph" / "plans" / "unsafe-current-plan-implementation-notes.html"
    active_notes.parent.mkdir(parents=True, exist_ok=True)
    active_notes.write_text(
        primary_notes.read_text(encoding="utf-8").replace("</main>", "<script>alert('unsafe')</script></main>"),
        encoding="utf-8",
    )
    primary_notes.unlink()
    (primary / ".ralph" / "plans" / "implementation-index.json").unlink()
    (primary / ".ralph" / "plans" / "implementation-index.md").unlink()

    result = run(
        [sys.executable, str(CONSOLIDATE), "--active-root", str(active), "--primary-root", str(primary), "--apply"],
        cwd=ROOT,
        env=env,
    )

    assert result.returncode == 1
    report = json.loads(result.stdout)
    by_slug = {item["slug"]: item for item in report["records"]}
    assert by_slug["unsafe-current-plan"]["schema"] == "invalid"
    assert "unsafe implementation notes HTML is not allowed" in by_slug["unsafe-current-plan"]["schema_error"]
    assert "conflicts must be resolved" in result.stderr
    assert not primary_notes.exists()
    assert not (primary / ".ralph" / "plans" / "implementation-index.json").exists()
    assert not (primary / ".ralph" / "plans" / "implementation-notes-consolidated.html").exists()
    assert not (primary / ".ralph" / "plans" / "implementation-notes-consolidated.md").exists()
