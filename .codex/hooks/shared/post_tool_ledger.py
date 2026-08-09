"""Bounded JSONL persistence used by the consolidated PostToolUse hook."""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

from .paths import ralph_home
from .persistence_metrics import WriteResult

DEFAULT_JSONL_MAX_BYTES = 2 * 1024 * 1024


def jsonl_max_bytes(name: str) -> int:
    try:
        configured = int(os.environ.get(name, str(DEFAULT_JSONL_MAX_BYTES)))
    except (TypeError, ValueError):
        configured = DEFAULT_JSONL_MAX_BYTES
    return max(32 * 1024, min(configured, 16 * 1024 * 1024))


def rotate_jsonl(path: Path, maximum: int) -> None:
    try:
        if not path.exists() or path.stat().st_size < maximum:
            return
        rotated = path.with_name(f"{path.name}.1")
        if rotated.is_symlink():
            return
        with contextlib.suppress(FileNotFoundError):
            rotated.unlink()
        os.replace(path, rotated)
    except OSError:
        return


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
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if root.is_symlink() or cost.is_symlink():
            return False
        cost.mkdir(exist_ok=True, mode=0o700)
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(lock_path, flags, 0o600)
        with os.fdopen(fd, "a+", encoding="utf-8") as lock:
            if fcntl is not None:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            rotate_jsonl(path, jsonl_max_bytes("RALPH_TOOL_LEDGER_MAX_BYTES"))
            encoded = (json.dumps(event, ensure_ascii=True, sort_keys=True) + "\n").encode("utf-8")
            output = os.open(
                path,
                os.O_CREAT | os.O_APPEND | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            try:
                os.write(output, encoded)
            finally:
                os.close(output)
            if fcntl is not None:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return WriteResult(changed=True, bytes_written=len(encoded), files_written=(path.name,), appends=1)
    except (OSError, TypeError, ValueError):
        return WriteResult.unknown()


__all__ = ["append_cost_event", "jsonl_max_bytes", "rotate_jsonl"]
