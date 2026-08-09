"""Dedicated paths for the canonical implementation-progress store.

This module intentionally does not reuse or widen the legacy implementation
notes path validator.  The new store has one write boundary: the primary
checkout's ``.local-notes/ralph/implementation`` directory.
"""

from __future__ import annotations

import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path


STORE_RELATIVE = Path(".local-notes") / "ralph" / "implementation"
MAX_PLAN_ID_LENGTH = 180
MAX_PLAN_DEPTH = 8


class StorePathError(ValueError):
    """Raised when a store path cannot be proven to be safe and canonical."""


@dataclass(frozen=True)
class StorePaths:
    primary_root: Path
    root: Path
    manifest: Path
    manifest_lock: Path
    unplanned_events: Path
    plans_root: Path

    def for_plan(self, plan_id: str) -> "PlanPaths":
        components = validate_plan_id(plan_id)
        plan_root = self.plans_root.joinpath(*components)
        assert_inside_store(plan_root, self.root)
        return PlanPaths(
            plan_id="/".join(components),
            root=plan_root,
            state=plan_root / "state.json",
            events=plan_root / "events.jsonl",
            state_lock=plan_root / "state.lock",
        )


@dataclass(frozen=True)
class PlanPaths:
    plan_id: str
    root: Path
    state: Path
    events: Path
    state_lock: Path


def resolve_primary_checkout_root(
    active_root: Path | str | None = None,
    primary_root: Path | str | None = None,
) -> Path:
    """Return the real main checkout for the active Git repository.

    The resolver is deliberately narrow.  It accepts an explicit primary only
    when Git proves that it is the main checkout for the same repository as
    ``active_root``.  A linked worktree, an unrelated repository, or a path
    that is a symlink alias is rejected before any store path is returned.
    """

    # An explicit primary is also a sufficient repository anchor.  Avoid
    # comparing it to the caller's current directory when this helper is used
    # by a standalone maintenance command or a fixture.
    active = _existing_directory(Path(active_root or primary_root or Path.cwd()), "active checkout")
    active_top, active_git_dir, common_dir = _git_identity(active)
    candidates = _worktree_candidates(active_top, common_dir)
    if primary_root is not None:
        explicit = _existing_directory(Path(primary_root), "primary checkout")
        _reject_symlink_components(explicit)
        explicit_top, explicit_git_dir, explicit_common = _git_identity(explicit)
        if explicit_common != common_dir:
            raise StorePathError("primary checkout belongs to a different Git repository")
        if explicit_git_dir != explicit_common:
            raise StorePathError("implementation store requires the main checkout, not a linked worktree")
        if explicit_top != explicit:
            raise StorePathError("primary checkout path is not the Git top-level directory")
        if candidates and explicit not in candidates:
            raise StorePathError("explicit primary checkout is not the repository's canonical worktree")
        return explicit

    if candidates:
        if len(candidates) != 1:
            raise StorePathError("repository has ambiguous main checkout candidates")
        return candidates[0]
    if active_git_dir == common_dir:
        return active_top
    raise StorePathError("could not resolve a primary checkout for the linked worktree")


def resolve_store_paths(
    active_root: Path | str | None = None,
    primary_root: Path | str | None = None,
) -> StorePaths:
    """Resolve the store layout without creating any files or directories."""

    primary = resolve_primary_checkout_root(active_root=active_root, primary_root=primary_root)
    _reject_symlink_components(primary)
    root = primary / STORE_RELATIVE
    _validate_store_boundary(root, primary)
    return StorePaths(
        primary_root=primary,
        root=root,
        manifest=root / "manifest.json",
        manifest_lock=root / "manifest.lock",
        unplanned_events=root / "unplanned-events.jsonl",
        plans_root=root / "plans",
    )


def validate_plan_id(plan_id: str) -> tuple[str, ...]:
    """Validate a relative plan identifier, allowing bounded nested plans."""

    if not isinstance(plan_id, str) or not plan_id or len(plan_id) > MAX_PLAN_ID_LENGTH:
        raise StorePathError("plan id is empty or exceeds the path limit")
    if "\x00" in plan_id or "\\" in plan_id or plan_id.startswith("/"):
        raise StorePathError("plan id contains an invalid path character")
    parts = tuple(plan_id.split("/"))
    if len(parts) > MAX_PLAN_DEPTH or any(not part or part in {".", ".."} for part in parts):
        raise StorePathError("plan id contains an invalid component")
    for part in parts:
        if part.startswith("~") or any(ord(char) < 32 for char in part):
            raise StorePathError("plan id contains an invalid component")
        if part in {"manifest.json", "manifest.lock", "unplanned-events.jsonl"}:
            raise StorePathError("plan id collides with a store file")
    return parts


def assert_inside_store(path: Path, store_root: Path) -> None:
    """Prove that ``path`` is lexically inside the exact store boundary."""

    try:
        path.relative_to(store_root)
    except ValueError as exc:
        raise StorePathError("path escapes the implementation store boundary") from exc
    _validate_store_boundary(path, store_root.parent.parent.parent)


def _validate_store_boundary(path: Path, primary_root: Path) -> None:
    try:
        path.relative_to(primary_root)
    except ValueError as exc:
        raise StorePathError("store path escapes the primary checkout") from exc
    # The relative path is fixed for the root.  For descendants, reject any
    # pre-existing symlink in every component without resolving aliases.
    _reject_symlink_components(path, allow_missing=True)
    if path != primary_root and not path.is_relative_to(primary_root / STORE_RELATIVE):
        raise StorePathError("path is outside the exact implementation store")


def _existing_directory(path: Path, label: str) -> Path:
    if not path.exists() or not path.is_dir():
        raise StorePathError(f"{label} does not exist as a directory")
    _reject_symlink_components(path)
    return path.absolute()


def _reject_symlink_components(path: Path, *, allow_missing: bool = False) -> None:
    """Reject symlinks in an existing prefix or at the final target."""

    absolute = path.absolute()
    parts = absolute.parts
    current = Path(parts[0])
    for part in parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            if allow_missing:
                continue
            raise StorePathError(f"store path component does not exist: {current}")
        except OSError as exc:
            raise StorePathError(f"cannot inspect store path component: {current}") from exc
        if os.path.islink(current) or stat.S_ISLNK(info.st_mode):
            raise StorePathError(f"symlink is not allowed in store path: {current}")


def _run_git(cwd: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StorePathError(f"unable to inspect Git repository: {exc}") from exc
    if result.returncode != 0:
        raise StorePathError(f"Git repository inspection failed: {result.stderr.strip() or result.returncode}")
    return result.stdout.strip()


def _git_identity(root: Path) -> tuple[Path, Path, Path]:
    top = Path(_run_git(root, "rev-parse", "--show-toplevel")).absolute()
    git_dir_raw = _run_git(root, "rev-parse", "--git-dir")
    common_raw = _run_git(root, "rev-parse", "--git-common-dir")
    git_dir = (top / git_dir_raw).absolute() if not os.path.isabs(git_dir_raw) else Path(git_dir_raw).absolute()
    common_dir = (top / common_raw).absolute() if not os.path.isabs(common_raw) else Path(common_raw).absolute()
    if not top.exists() or not git_dir.exists() or not common_dir.exists():
        raise StorePathError("Git repository metadata is incomplete")
    return top, git_dir, common_dir


def _worktree_candidates(active_top: Path, common_dir: Path) -> list[Path]:
    output = _run_git(active_top, "worktree", "list", "--porcelain")
    paths: list[Path] = []
    current: Path | None = None
    for line in output.splitlines() + [""]:
        if line.startswith("worktree "):
            current = Path(line.split(" ", 1)[1]).absolute()
        elif not line and current is not None:
            try:
                _top, git_dir, candidate_common = _git_identity(current)
            except StorePathError:
                current = None
                continue
            if git_dir == common_dir and candidate_common == common_dir:
                paths.append(current)
            current = None
    return list(dict.fromkeys(paths))


def ensure_directory_chain(path: Path, *, mode: int = 0o700) -> None:
    """Create a store directory chain securely, without following aliases."""

    _reject_symlink_components(path, allow_missing=True)
    _reject_symlink_components(path.parent, allow_missing=True)
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
        if current == current.parent:
            break
    _reject_symlink_components(current)
    if current.exists():
        directory_stat(current)
        os.chmod(current, mode)
    for directory in reversed(missing):
        directory.mkdir(mode=mode)
        _reject_symlink_components(directory)
        os.chmod(directory, mode)


def ensure_store_layout(paths: StorePaths) -> None:
    """Create only the new store directories; callers own file publication."""

    _validate_store_boundary(paths.root, paths.primary_root)
    if paths.root.exists():
        directory_stat(paths.root)
        os.chmod(paths.root, 0o700)
    ensure_directory_chain(paths.root, mode=0o700)
    if paths.plans_root.exists():
        directory_stat(paths.plans_root)
        os.chmod(paths.plans_root, 0o700)
    ensure_directory_chain(paths.plans_root, mode=0o700)


def regular_file_stat(path: Path) -> os.stat_result:
    """Return a safe regular-file stat, rejecting symlinks and hardlinks."""

    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise StorePathError(f"file does not exist: {path}") from exc
    if os.path.islink(path) or not stat.S_ISREG(info.st_mode):
        raise StorePathError(f"store file must be a regular non-symlink file: {path}")
    if info.st_nlink != 1:
        raise StorePathError(f"hardlinked store files are not allowed: {path}")
    return info


def directory_stat(path: Path) -> os.stat_result:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise StorePathError(f"directory does not exist: {path}") from exc
    if os.path.islink(path) or not stat.S_ISDIR(info.st_mode):
        raise StorePathError(f"store directory must be a real directory: {path}")
    return info
