"""Bounded JSONL persistence used by the consolidated PostToolUse hook."""
from __future__ import annotations

import contextlib
import json
import os
import stat
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

from .paths import ralph_home
from .persistence_metrics import WriteResult

DEFAULT_JSONL_MAX_BYTES = 2 * 1024 * 1024
MAX_RECORD_BYTES = 256 * 1024


def jsonl_max_bytes(name: str) -> int:
    try:
        configured = int(os.environ.get(name, str(DEFAULT_JSONL_MAX_BYTES)))
    except (TypeError, ValueError):
        configured = DEFAULT_JSONL_MAX_BYTES
    return max(32 * 1024, min(configured, 16 * 1024 * 1024))


def rotate_jsonl(path: Path, maximum: int) -> None:
    try:
        info = _safe_file(path)
        if info is None or info.st_size < maximum:
            return
        rotated = path.with_name(f"{path.name}.1")
        _safe_file(rotated, allow_missing=True)
        if rotated.exists():
            rotated.unlink()
        _safe_path_components(path.parent)
        os.replace(path, rotated)
        _fsync_directory(path.parent)
    except OSError:
        return


def _safe_file(path: Path, *, allow_missing: bool = False) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        if allow_missing:
            return None
        raise
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise OSError("tool ledger target is not a regular non-aliased file")
    return info


def _safe_path_components(path: Path, *, allow_missing: bool = False) -> None:
    absolute = path.absolute()
    current = Path(absolute.parts[0])
    for part in absolute.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            if allow_missing:
                continue
            raise OSError(f"tool ledger path component does not exist: {current}")
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise OSError(f"tool ledger path component is unsafe: {current}")


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _write_all(fd: int, encoded: bytes) -> None:
    view = memoryview(encoded)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short tool ledger write")
        view = view[written:]


def _path_has_symlink(path: Path) -> bool:
    candidate = Path(os.path.abspath(os.fspath(path)))
    for part in (candidate, *candidate.parents):
        if part.exists() and part.is_symlink():
            return True
        if part == part.parent:
            break
    return False


def append_cost_event(event: dict[str, Any]) -> WriteResult:
    """Append one cost record under a single bounded cross-project lock."""
    root = ralph_home()
    if _path_has_symlink(root):
        return WriteResult.unknown()
    cost = root / "cost"
    path = cost / "tool-ledger.jsonl"
    lock_path = cost / ".tool-ledger.lock"
    try:
        _safe_path_components(root, allow_missing=True)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        _safe_path_components(root)
        _safe_path_components(cost, allow_missing=True)
        cost.mkdir(exist_ok=True, mode=0o700)
        _safe_path_components(cost)
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(lock_path, flags, 0o600)
        with os.fdopen(fd, "a+b") as lock:
            lock_info = os.fstat(lock.fileno())
            if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_nlink != 1:
                return WriteResult.unknown()
            os.fchmod(lock.fileno(), 0o600)
            if fcntl is not None:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            encoded = (json.dumps(event, ensure_ascii=True, sort_keys=True) + "\n").encode("utf-8")
            if len(encoded) > MAX_RECORD_BYTES:
                return WriteResult.unknown()
            maximum = jsonl_max_bytes("RALPH_TOOL_LEDGER_MAX_BYTES")
            rotate_jsonl(path, maximum)
            _safe_file(path, allow_missing=True)
            existed = path.exists()
            output = os.open(
                path,
                os.O_CREAT | os.O_APPEND | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            try:
                info = os.fstat(output)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size + len(encoded) > maximum:
                    return WriteResult.unknown()
                _write_all(output, encoded)
                os.fchmod(output, 0o600)
                os.fsync(output)
            finally:
                os.close(output)
            if not existed:
                _fsync_directory(cost)
            if fcntl is not None:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return WriteResult(changed=True, bytes_written=len(encoded), files_written=(path.name,), appends=1)
    except (OSError, TypeError, ValueError):
        return WriteResult.unknown()


__all__ = ["append_cost_event", "jsonl_max_bytes", "rotate_jsonl"]
