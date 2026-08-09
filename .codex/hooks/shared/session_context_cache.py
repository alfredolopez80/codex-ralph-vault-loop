"""Small, path-hardened cache for SessionStart context fingerprints."""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - POSIX is the supported hook host.
    fcntl = None  # type: ignore[assignment]

from .active_context import ActiveContext, project_runtime_root
from .paths import now_iso, ralph_home


SCHEMA_VERSION = 1
STATE_DIR = "session-context"
STATE_FILE = "state.json"
LOCK_FILE = "state.lock"
DEFAULT_TTL_SECONDS = 24 * 60 * 60
DEFAULT_MAX_SESSIONS = 32


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _state_dir(context: ActiveContext) -> Path:
    return project_runtime_root(context) / STATE_DIR


def _safe_directory(context: ActiveContext, *, create: bool) -> Path | None:
    root = ralph_home().expanduser()
    directory = _state_dir(context)
    try:
        if not root.is_absolute() or root.is_symlink():
            return None
        relative = directory.relative_to(root)
        current = root
        if create:
            current.mkdir(parents=True, exist_ok=True, mode=0o700)
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return None
            if create:
                current.mkdir(exist_ok=True, mode=0o700)
    except (OSError, ValueError):
        return None
    return directory


def _safe_path(parent: Path, child: Path) -> Path | None:
    try:
        if child.parent != parent or child.is_symlink() or parent.is_symlink():
            return None
    except OSError:
        return None
    return child


def state_path(context: ActiveContext) -> Path:
    return _state_dir(context) / STATE_FILE


def _quarantine(path: Path) -> None:
    if not path.exists() or path.is_symlink():
        return
    target = path.with_name(f"{path.stem}.invalid.{int(datetime.now(UTC).timestamp())}.json")
    with contextlib.suppress(OSError):
        os.replace(path, target)


def _empty_state() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "updated_at": now_iso(), "sessions": {}}


def read_state(context: ActiveContext) -> dict[str, Any]:
    directory = _safe_directory(context, create=False)
    if directory is None:
        return _empty_state()
    path = _safe_path(directory, state_path(context))
    if path is None or not path.exists() or path.is_symlink():
        return _empty_state()
    try:
        if path.stat().st_size > 64 * 1024:
            _quarantine(path)
            return _empty_state()
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        _quarantine(path)
        return _empty_state()
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        _quarantine(path)
        return _empty_state()
    sessions = data.get("sessions")
    if not isinstance(sessions, dict):
        _quarantine(path)
        return _empty_state()
    return {"schema_version": SCHEMA_VERSION, "updated_at": data.get("updated_at", ""), "sessions": sessions}


def _prune(state: dict[str, Any]) -> dict[str, Any]:
    sessions = state.get("sessions")
    if not isinstance(sessions, dict):
        sessions = {}
    ttl = _env_int("RALPH_SESSION_CONTEXT_TTL_SECONDS", DEFAULT_TTL_SECONDS)
    cutoff = datetime.now(UTC) - timedelta(seconds=ttl)
    retained: list[tuple[str, dict[str, Any]]] = []
    for key, value in sessions.items():
        if not isinstance(value, dict):
            continue
        timestamp = value.get("updated_at")
        try:
            parsed = datetime.fromisoformat(str(timestamp))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
        if parsed.astimezone(UTC) >= cutoff:
            retained.append((str(key), value))
    retained.sort(key=lambda item: str(item[1].get("updated_at", "")), reverse=True)
    limit = _env_int("RALPH_SESSION_CONTEXT_MAX_ENTRIES", DEFAULT_MAX_SESSIONS)
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": now_iso(),
        "sessions": dict(retained[:limit]),
    }


def write_state(context: ActiveContext, state: dict[str, Any]) -> bool:
    directory = _safe_directory(context, create=True)
    if directory is None:
        return False
    path = _safe_path(directory, state_path(context))
    if path is None:
        return False
    try:
        clean = _prune(state)
        payload = json.dumps(clean, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
        fd, temporary = tempfile.mkstemp(prefix=".state.", suffix=".tmp", dir=directory)
        temporary_path = Path(temporary)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                temporary_path.unlink()
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)
        return True
    except OSError:
        return False


@contextmanager
def state_lock(context: ActiveContext) -> Iterator[bool]:
    directory = _safe_directory(context, create=True)
    if directory is None:
        yield False
        return
    lock = _safe_path(directory, directory / LOCK_FILE)
    if lock is None:
        yield False
        return
    try:
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(lock, flags, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            with contextlib.suppress(OSError):
                os.chmod(lock, 0o600)
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield True
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        yield False


def session_entry(state: dict[str, Any], session_id: str) -> dict[str, Any]:
    sessions = state.get("sessions")
    if not isinstance(sessions, dict):
        return {}
    entry = sessions.get(session_id)
    return dict(entry) if isinstance(entry, dict) else {}


__all__ = ["SCHEMA_VERSION", "read_state", "session_entry", "state_lock", "state_path", "write_state"]
