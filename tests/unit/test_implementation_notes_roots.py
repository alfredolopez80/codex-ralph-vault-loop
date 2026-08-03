from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "scripts" / "plans"
HOOKS = ROOT / ".codex" / "hooks"
if str(PLANS) not in sys.path:
    sys.path.insert(0, str(PLANS))
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

import implementation_notes_lib as notes_lib
from implementation_notes_guard import canonical_plan_for_guard
from implementation_notes_lib import ImplementationNotesError, resolve_roots


def git(cwd: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def make_repo(tmp_path: Path) -> Path:
    primary = tmp_path / "primary" / "canonical-project"
    primary.mkdir(parents=True)
    git(primary, "init")
    git(primary, "config", "user.email", "test@example.invalid")
    git(primary, "config", "user.name", "Test User")
    (primary / "README.md").write_text("# fixture\n", encoding="utf-8")
    git(primary, "add", "README.md")
    git(primary, "commit", "-m", "init")
    return primary


def add_worktree(primary: Path, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    git(primary, "worktree", "add", "--detach", str(path), "HEAD")
    return path


def test_resolve_roots_uses_common_git_identity_for_renamed_linked_worktree(tmp_path: Path) -> None:
    primary = make_repo(tmp_path)
    active = add_worktree(primary, tmp_path / "alternate-location" / "name-does-not-match-primary")

    roots = resolve_roots(active_root=active)

    assert roots.active_worktree_root == active.resolve()
    assert roots.primary_repo_root == primary.resolve()
    assert roots.git_common_dir == (primary / ".git").resolve()
    assert roots.resolution_method == "git-common-dir"


def test_resolve_roots_finds_primary_for_linked_worktree_outside_codex_directory(tmp_path: Path) -> None:
    primary = make_repo(tmp_path)
    active = add_worktree(primary, tmp_path / "non-codex-worktrees" / "review-copy")

    roots = resolve_roots(active_root=active)

    assert roots.primary_repo_root == primary.resolve()
    assert roots.primary_repo_root != roots.active_worktree_root
    assert roots.resolution_method == "git-common-dir"


def test_resolve_roots_normalizes_symlinked_explicit_primary(tmp_path: Path) -> None:
    primary = make_repo(tmp_path)
    active = add_worktree(primary, tmp_path / "linked" / "feature-copy")
    primary_alias = tmp_path / "primary-alias"
    primary_alias.symlink_to(primary, target_is_directory=True)

    roots = resolve_roots(active_root=active, primary_root=primary_alias)

    assert roots.primary_repo_root == primary.resolve()
    assert roots.resolution_method == "explicit-primary"


def test_resolve_roots_rejects_explicit_primary_from_different_repository(tmp_path: Path) -> None:
    primary = make_repo(tmp_path / "first")
    active = add_worktree(primary, tmp_path / "first" / "linked" / "feature-copy")
    unrelated = make_repo(tmp_path / "second")

    with pytest.raises(ImplementationNotesError, match="different Git repository"):
        resolve_roots(active_root=active, primary_root=unrelated)


def test_resolve_roots_rejects_explicit_linked_worktree_as_primary(tmp_path: Path) -> None:
    primary = make_repo(tmp_path)
    active = add_worktree(primary, tmp_path / "linked" / "feature-copy")

    with pytest.raises(ImplementationNotesError, match="main checkout, not a linked worktree"):
        resolve_roots(active_root=active, primary_root=active)


def test_resolve_roots_rejects_explicit_primary_under_codex_worktrees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_root = tmp_path / "home" / ".codex" / "worktrees"
    monkeypatch.setattr(notes_lib, "CODEX_WORKTREE_ROOT", codex_root)
    primary = make_repo(codex_root)
    active = add_worktree(primary, tmp_path / "linked" / "feature-copy")

    with pytest.raises(ImplementationNotesError, match="cannot be under ~/.codex/worktrees"):
        resolve_roots(active_root=active, primary_root=primary)


def test_resolve_roots_fails_closed_when_canonical_root_is_ambiguous(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    primary = make_repo(tmp_path)
    alternate = tmp_path / "alternate-primary"
    alternate.mkdir()
    monkeypatch.setattr(notes_lib, "_canonical_primary_candidates", lambda *_: [primary, alternate])

    with pytest.raises(ImplementationNotesError, match="ambiguous canonical local repo roots"):
        resolve_roots(active_root=primary)


def test_guard_canonicalizes_nested_plan_from_external_linked_worktree(tmp_path: Path) -> None:
    primary = make_repo(tmp_path)
    active = add_worktree(primary, tmp_path / "ordinary-linked" / "active-copy")
    active_plan = active / ".ralph" / "plans" / "nested" / "feature.md"
    canonical_plan = primary / ".ralph" / "plans" / "nested" / "feature.md"
    active_plan.parent.mkdir(parents=True)
    canonical_plan.parent.mkdir(parents=True)
    active_plan.write_text("# Feature\n", encoding="utf-8")
    canonical_plan.write_text("# Feature\n", encoding="utf-8")

    roots = resolve_roots(active_root=active)

    assert canonical_plan_for_guard(active_plan, roots) == canonical_plan.resolve()


def test_guard_rejects_external_linked_plan_without_canonical_copy(tmp_path: Path) -> None:
    primary = make_repo(tmp_path)
    active = add_worktree(primary, tmp_path / "ordinary-linked" / "active-copy")
    active_plan = active / ".ralph" / "plans" / "feature.md"
    active_plan.parent.mkdir(parents=True)
    active_plan.write_text("# Feature\n", encoding="utf-8")

    roots = resolve_roots(active_root=active)

    with pytest.raises(ImplementationNotesError, match="only in an ephemeral Codex worktree or other linked worktree"):
        canonical_plan_for_guard(active_plan, roots)
