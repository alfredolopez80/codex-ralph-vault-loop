from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
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
    assert "unsafe legacy HTML is not allowed" in by_slug["unsafe-legacy-plan"]["schema_error"]
    assert "conflicts must be resolved" in result.stderr
    assert not (primary / ".ralph" / "plans" / "implementation-index.json").exists()
    assert not (primary / ".ralph" / "plans" / "implementation-notes-consolidated.html").exists()
    assert not (primary / ".ralph" / "plans" / "implementation-notes-consolidated.md").exists()
