from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


PATCH_PATH_RE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.MULTILINE)


def root() -> Path:
    override = os.environ.get("CODEX_LOCAL_GRANT_ROOT")
    return Path(override).expanduser() if override else Path.home() / ".ralph-codex" / "local-grants"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


def targets(patch: str, cwd: Path) -> list[Path] | None:
    raw_paths = PATCH_PATH_RE.findall(patch)
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
    grant_path = root() / f"{payload_hash}.json"
    try:
        grant_root = root()
        if grant_root.is_symlink() or grant_root.stat().st_mode & 0o077:
            return False
        if grant_path.is_symlink() or grant_path.stat().st_mode & 0o077:
            return False
        grant = json.loads(grant_path.read_text(encoding="utf-8"))
        expiry = datetime.fromisoformat(grant["expires_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return bool(
        grant.get("kind") == "local-minikube-patch"
        and grant.get("sha256") == payload_hash
        and grant.get("targets") == sorted(str(path) for path in patch_targets)
        and expiry.tzinfo is not None
        and expiry > datetime.now(timezone.utc)
    )
