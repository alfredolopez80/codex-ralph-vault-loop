from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


PATCH_PATH_RE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.MULTILINE)
PATCH_MOVE_RE = re.compile(r"^\*\*\* Move to: (.+)$", re.MULTILINE)
MARKER_TTL_SECONDS = 900


@dataclass(frozen=True)
class PatchGrant:
    patch_sha256: str
    cwd: str
    targets: tuple[str, ...]
    approval_sha256: str

    @property
    def marker_name(self) -> str:
        return f"patch-{self.approval_sha256}"


def root() -> Path:
    override = os.environ.get("CODEX_LOCAL_GRANT_ROOT")
    return Path(override).expanduser() if override else Path.home() / ".ralph-codex" / "local-grants"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def marker_allows(marker_name: str) -> bool:
    marker_path = root() / f"{marker_name}.approved"
    try:
        marker_root = root()
        if marker_root.is_symlink() or marker_root.stat().st_mode & 0o077:
            return False
        if marker_path.is_symlink() or marker_path.stat().st_mode & 0o077:
            return False
        age = datetime.now(timezone.utc).timestamp() - marker_path.stat().st_mtime
        if age < 0 or age > MARKER_TTL_SECONDS or marker_path.stat().st_size != 0:
            return False
        marker_path.unlink()
    except OSError:
        return False
    return True


def allows_command(command: str) -> bool:
    return marker_allows(f"command-{digest(command)}")


def is_git_tracked(path: Path) -> bool:
    probe = path if path.is_dir() else path.parent
    root_result = subprocess.run(
        ["git", "-C", str(probe), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if root_result.returncode != 0:
        return False
    repo_root = Path(root_result.stdout.strip()).resolve()
    try:
        relative = path.relative_to(repo_root)
    except ValueError:
        return False
    tracked = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "--error-unmatch", "--", str(relative)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return tracked.returncode == 0


def _git_root(cwd: Path) -> Path | None:
    result = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return Path(result.stdout.strip()).resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _normalized_target_paths(cwd: Path, raw_paths: list[str]) -> tuple[str, ...] | None:
    repo_root = _git_root(cwd)
    if repo_root is None or not raw_paths:
        return None
    normalized: list[str] = []
    for raw_path in raw_paths:
        candidate = Path(raw_path.strip()).expanduser()
        candidate = candidate if candidate.is_absolute() else cwd / candidate
        absolute = candidate.absolute()
        existing = absolute
        while not existing.exists() and existing != existing.parent:
            existing = existing.parent
        if existing.is_symlink():
            return None
        try:
            relative = absolute.resolve(strict=False).relative_to(repo_root)
        except (OSError, RuntimeError, ValueError):
            return None
        if not relative.parts or relative == Path("."):
            return None
        normalized.append(relative.as_posix())
    if len(set(normalized)) != len(normalized):
        return None
    return tuple(sorted(normalized))


def patch_grant(patch: str, cwd: Path) -> PatchGrant | None:
    raw_paths = [*PATCH_PATH_RE.findall(patch), *PATCH_MOVE_RE.findall(patch)]
    targets = _normalized_target_paths(cwd, raw_paths)
    if targets is None:
        return None
    patch_sha256 = digest(patch)
    canonical_cwd = str(cwd.resolve())
    subject = json.dumps(
        {"cwd": canonical_cwd, "patch_sha256": patch_sha256, "targets": targets},
        separators=(",", ":"),
        sort_keys=True,
    )
    return PatchGrant(
        patch_sha256=patch_sha256,
        cwd=canonical_cwd,
        targets=targets,
        approval_sha256=digest(subject),
    )


def patch_grant_from_request(patch_sha256: str, cwd: Path, targets: list[str]) -> PatchGrant | None:
    if not re.fullmatch(r"[0-9a-f]{64}", patch_sha256):
        return None
    repo_root = _git_root(cwd)
    if repo_root is None or not targets:
        return None
    normalized_targets = _normalized_target_paths(repo_root, targets)
    if normalized_targets is None:
        return None
    canonical_cwd = str(cwd.resolve())
    subject = json.dumps(
        {"cwd": canonical_cwd, "patch_sha256": patch_sha256, "targets": normalized_targets},
        separators=(",", ":"),
        sort_keys=True,
    )
    return PatchGrant(
        patch_sha256=patch_sha256,
        cwd=canonical_cwd,
        targets=normalized_targets,
        approval_sha256=digest(subject),
    )


def allows_patch(patch: str, cwd: Path) -> PatchGrant | None:
    grant = patch_grant(patch, cwd)
    if grant is None or not marker_allows(grant.marker_name):
        return None
    return grant


def create_patch_marker(grant: PatchGrant) -> Path:
    grant_root = root()
    grant_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(grant_root, 0o700)
    marker = grant_root / f"{grant.marker_name}.approved"
    marker.write_text("", encoding="utf-8")
    os.chmod(marker, 0o600)
    return marker


def targets(patch: str, cwd: Path) -> list[Path] | None:
    raw_paths = [*PATCH_PATH_RE.findall(patch), *PATCH_MOVE_RE.findall(patch)]
    if not raw_paths:
        return None
    resolved: list[Path] = []
    for raw_path in raw_paths:
        candidate = Path(raw_path.strip()).expanduser()
        candidate = candidate if candidate.is_absolute() else cwd / candidate
        absolute = candidate.absolute()
        existing = absolute
        while not existing.exists() and existing != existing.parent:
            existing = existing.parent
        if existing.is_symlink():
            return None
        candidate = absolute.resolve(strict=False)
        if ".local-notes" not in candidate.parts or candidate == Path(candidate.anchor) or is_git_tracked(candidate):
            return None
        resolved.append(candidate)
    return resolved


def allows(patch: str, cwd: Path) -> bool:
    patch_targets = targets(patch, cwd)
    if not patch_targets:
        return False
    payload_hash = digest(patch)
    return marker_allows(payload_hash)
