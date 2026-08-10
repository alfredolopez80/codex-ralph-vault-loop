"""Path-hardened, rotating storage for normalized runtime events."""
from __future__ import annotations

import contextlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Mapping

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

from .paths import ralph_home
from .persistence_metrics import WriteResult

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
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not home.is_dir() or home.is_symlink():
            return None
        home.chmod(0o700)
        current = home
        for part in ("projects", project_id, "observability"):
            current = current / part
            if current.is_symlink():
                return None
            current.mkdir(exist_ok=True, mode=0o700)
            if not current.is_dir() or current.is_symlink():
                return None
            current.chmod(0o700)
        return current
    except OSError:
        return None


def event_path(project_id: str) -> Path | None:
    root = _safe_root(project_id)
    return root / "runtime-events.jsonl" if root is not None else None


def _safe_file(path: Path, *, allow_missing: bool = False) -> os.stat_result | None:
    """Return an identity snapshot for a private, non-aliased regular file."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        if allow_missing:
            return None
        raise
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise OSError("runtime event target is not a regular non-aliased file")
    return info


def _rotate(path: Path, *, max_bytes: int, max_files: int) -> None:
    try:
        current = _safe_file(path)
        if current is None or current.st_size < max_bytes:
            return
    except OSError:
        return
    for index in range(max_files - 1, 0, -1):
        source = path.with_name(f"{path.name}.{index}")
        target = path.with_name(f"{path.name}.{index + 1}")
        with contextlib.suppress(OSError):
            _safe_file(source)
            source.unlink() if index == max_files - 1 else os.replace(source, target)
    if max_files == 1:
        with contextlib.suppress(OSError):
            path.with_name(f"{path.name}.1").unlink()
    with contextlib.suppress(OSError):
        _safe_file(path)
        os.replace(path, path.with_name(f"{path.name}.1"))


def append_normalized(project_id: str, event: Mapping[str, object], *, max_event_bytes: int) -> WriteResult:
    path = event_path(project_id)
    if path is None or fcntl is None:
        return WriteResult.unknown()
    lock_path = path.with_name(f".{path.name}.lock")
    try:
        _safe_file(lock_path, allow_missing=True)
        _safe_file(path, allow_missing=True)
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(lock_path, flags, 0o600)
        with os.fdopen(fd, "a+", encoding="utf-8") as lock:
            lock_info = os.fstat(lock.fileno())
            if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_nlink != 1:
                return WriteResult.unknown()
            os.fchmod(lock.fileno(), 0o600)
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            max_bytes, max_files = _runtime_limits()
            encoded = (json.dumps(dict(event), ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            if len(encoded) > max_event_bytes:
                return WriteResult.unknown()
            _rotate(path, max_bytes=max_bytes, max_files=max_files)
            _safe_file(path, allow_missing=True)
            output = os.open(
                path,
                os.O_CREAT | os.O_APPEND | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            try:
                info = os.fstat(output)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    return WriteResult.unknown()
                view = memoryview(encoded)
                while view:
                    written = os.write(output, view)
                    if written <= 0:
                        return WriteResult.unknown(changed=True)
                    view = view[written:]
                os.fchmod(output, 0o600)
                os.fsync(output)
            finally:
                os.close(output)
            # Keep the permission operation tied to the opened inode; a path
            # chmod after close would reintroduce a replace/race window.
            # Rotate immediately after a publication so the active file never
            # grows beyond the configured bound.  A single rotated file may
            # contain the boundary-crossing record, but the hot active path
            # remains bounded for the next reader.
            _rotate(path, max_bytes=max_bytes, max_files=max_files)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return WriteResult(changed=True, bytes_written=len(encoded), files_written=(path.name,), appends=1)
    except (OSError, TypeError, ValueError):
        return WriteResult.unknown()


__all__ = ["append_normalized", "event_path"]
