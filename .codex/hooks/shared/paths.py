from __future__ import annotations

import json
import os
import stat
import sys
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any

from .persistence_metrics import WriteResult

DEFAULT_RALPH_HOME = Path("~/.ralph-codex").expanduser()
MAX_APPEND_RECORD_BYTES = 256 * 1024
MAX_APPEND_FILE_BYTES = 8 * 1024 * 1024
MAX_HOOK_OUTPUT_BYTES = 64 * 1024


def repo_root() -> Path:
    override = os.environ.get("RALPH_REPO_ROOT")
    if override:
        return Path(override).expanduser()
    marker = Path(__file__).resolve().parents[1] / ".ralph-repo-root"
    if marker.exists():
        value = marker.read_text(encoding="utf-8").strip()
        if value:
            return Path(value).expanduser()
    return Path(__file__).resolve().parents[3]


REPO_ROOT = repo_root()


def ralph_home() -> Path:
    return Path(os.environ.get("RALPH_HOME", str(DEFAULT_RALPH_HOME))).expanduser()


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def ensure_runtime() -> Path:
    root = ralph_home()
    _safe_path_components(root, allow_missing=True)
    for relative in ("layers", "ledgers", "handoffs", "reports", "cost"):
        directory = root / relative
        _safe_path_components(directory, allow_missing=True)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        _safe_path_components(directory)
        directory.chmod(0o700)
    return root


def read_hook_input() -> dict[str, Any]:
    try:
        stream = getattr(sys.stdin, "buffer", sys.stdin)
        raw_value = stream.read(4 * 1024 * 1024 + 1)
        raw = raw_value.decode("utf-8", errors="replace") if isinstance(raw_value, bytes) else str(raw_value)
        if len(raw.encode("utf-8")) > 4 * 1024 * 1024:
            return {}
        if not raw.strip():
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def write_json(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_HOOK_OUTPUT_BYTES:
        print(json.dumps({"decision": "block", "reason": "hook response exceeded its bounded output limit."}, separators=(",", ":")))
        return
    print(encoded.decode("utf-8"))


def append_jsonl(path: Path, payload: dict[str, Any]) -> WriteResult:
    """Append one bounded JSON record and report its exact encoded size.

    Existing callers intentionally ignore the return value.  Returning a
    content-free result lets hot-path dispatchers account for writes without a
    recursive runtime scan while preserving the historical fail-open shape.
    """
    try:
        _safe_path_components(path.parent, allow_missing=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n").encode("utf-8")
        if len(encoded) > MAX_APPEND_RECORD_BYTES:
            return WriteResult.unknown()
        existed = path.exists()
        if existed:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size + len(encoded) > MAX_APPEND_FILE_BYTES:
                return WriteResult.unknown()
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size + len(encoded) > MAX_APPEND_FILE_BYTES:
                return WriteResult.unknown()
            view = memoryview(encoded)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    return WriteResult.unknown(changed=True)
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        _safe_path_components(path.parent)
        if not existed:
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return WriteResult(changed=True, bytes_written=len(encoded), files_written=(path.name,), appends=1)
    except (OSError, TypeError, ValueError):
        return WriteResult.unknown()


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
            raise OSError(f"path component does not exist: {current}")
        if stat.S_ISLNK(info.st_mode) and not _is_allowed_system_alias(current):
            raise OSError(f"path component is a symlink: {current}")
        if not _is_allowed_system_alias(current) and not stat.S_ISDIR(info.st_mode):
            raise OSError(f"path component is not a directory: {current}")


def _is_allowed_system_alias(path: Path) -> bool:
    """Allow only macOS's protected /var and /tmp aliases."""
    if sys.platform != "darwin" or not path.is_symlink():
        return False
    targets = {Path("/var"): Path("/private/var"), Path("/tmp"): Path("/private/tmp")}
    target = targets.get(path)
    return target is not None and path.resolve(strict=False) == target
