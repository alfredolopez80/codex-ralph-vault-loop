"""Path-hardened, rotating storage for normalized runtime events."""
from __future__ import annotations

import contextlib
import json
import os
import re
from pathlib import Path
from typing import Mapping

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

from .paths import ralph_home

PROJECT_ID_RE = re.compile(r"^p-[a-f0-9]{16}$")
DEFAULT_MAX_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_FILES = 3


def _runtime_limits() -> tuple[int, int]:
    try:
        max_bytes = int(os.environ.get("RALPH_RUNTIME_EVENTS_MAX_BYTES", DEFAULT_MAX_BYTES))
    except (TypeError, ValueError):
        max_bytes = DEFAULT_MAX_BYTES
    try:
        max_files = int(os.environ.get("RALPH_RUNTIME_EVENTS_MAX_FILES", DEFAULT_MAX_FILES))
    except (TypeError, ValueError):
        max_files = DEFAULT_MAX_FILES
    return max(32 * 1024, min(max_bytes, 32 * 1024 * 1024)), max(1, min(max_files, 16))


def _safe_root(project_id: str) -> Path | None:
    if not PROJECT_ID_RE.fullmatch(project_id):
        return None
    try:
        home = ralph_home()
        candidate = Path(os.path.abspath(os.fspath(home)))
        for part in (candidate, *candidate.parents):
            if part.is_symlink():
                return None
            if part == part.parent:
                break
        home = home.resolve(strict=False)
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        home.chmod(0o700)
        current = home
        for part in ("projects", project_id, "observability"):
            current = current / part
            if current.is_symlink():
                return None
            current.mkdir(exist_ok=True, mode=0o700)
            current.chmod(0o700)
        return current
    except OSError:
        return None


def event_path(project_id: str) -> Path | None:
    root = _safe_root(project_id)
    return root / "runtime-events.jsonl" if root is not None else None


def _rotate(path: Path, *, max_bytes: int, max_files: int) -> None:
    try:
        if not path.exists() or path.stat().st_size < max_bytes:
            return
    except OSError:
        return
    for index in range(max_files - 1, 0, -1):
        source = path.with_name(f"{path.name}.{index}")
        target = path.with_name(f"{path.name}.{index + 1}")
        with contextlib.suppress(OSError):
            source.unlink() if index == max_files - 1 else os.replace(source, target)
    if max_files == 1:
        with contextlib.suppress(OSError):
            path.with_name(f"{path.name}.1").unlink()
    with contextlib.suppress(OSError):
        os.replace(path, path.with_name(f"{path.name}.1"))


def append_normalized(project_id: str, event: Mapping[str, object], *, max_event_bytes: int) -> bool:
    path = event_path(project_id)
    if path is None or fcntl is None:
        return False
    lock_path = path.with_name(f".{path.name}.lock")
    try:
        if lock_path.is_symlink() or path.is_symlink():
            return False
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(lock_path, flags, 0o600)
        with os.fdopen(fd, "a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            max_bytes, max_files = _runtime_limits()
            _rotate(path, max_bytes=max_bytes, max_files=max_files)
            encoded = (json.dumps(dict(event), ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            if len(encoded) > max_event_bytes:
                return False
            output = os.open(
                path,
                os.O_CREAT | os.O_APPEND | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            try:
                os.write(output, encoded)
            finally:
                os.close(output)
            path.chmod(0o600)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return True
    except (OSError, TypeError, ValueError):
        return False


__all__ = ["append_normalized", "event_path"]
