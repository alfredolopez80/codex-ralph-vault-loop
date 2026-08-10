from __future__ import annotations

import json
import os
import stat
import tempfile
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .active_context import project_runtime_root
from .paths import ralph_home
from .persistence_metrics import WriteResult
from .stop_scope import SCHEMA_VERSION, StopScope, state_ttl_seconds

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


STATE_SCHEMA_VERSION = 1
DEFAULT_MAX_ENTRIES = 256
MAX_STATE_BYTES = 256 * 1024
MAX_EVENT_RECORD_BYTES = 256 * 1024
MAX_EVENT_FILE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class Reservation:
    allowed: bool
    count: int
    exhausted: bool
    evidence_fingerprint: str
    state_corrupt: bool = False
    storage_error: bool = False
    changed: bool = False
    bytes_written: int | None = 0
    files_written: tuple[str, ...] = ()
    replacements: int = 0
    fsync_publications: int = 0


def _now() -> float:
    return datetime.now(UTC).timestamp()


def _max_entries() -> int:
    raw = os.environ.get("RALPH_STOP_MAX_BUDGET_ENTRIES", str(DEFAULT_MAX_ENTRIES))
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_ENTRIES
    return max(8, min(value, 2048))


def _runtime_safe(path: Path, root: Path | None = None) -> bool:
    try:
        if path.is_symlink():
            return False
        root = (root or ralph_home()).expanduser()
        if not root.is_absolute() or root.is_symlink():
            return False
        try:
            relative = path.relative_to(root)
        except ValueError:
            return False
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return False
        return True
    except OSError:
        return False


def budget_path(scope: StopScope) -> Path:
    return project_runtime_root(scope.context) / "stop" / "continuation.json"


def fallback_budget_path(scope: StopScope) -> tuple[Path, Path] | None:
    configured = os.environ.get("CODEX_HOOK_STATE_ROOT", "").strip()
    if not configured or "\n" in configured:
        return None
    root = Path(configured).expanduser()
    if not root.is_absolute():
        return None
    project = "".join(char for char in scope.context.project_id if char.isalnum() or char in "._-")[:80] or "unknown"
    path = root / "ralph-stop" / project / "continuation.json"
    return root, path


def events_path(scope: StopScope, name: str = "stop-events.jsonl") -> Path:
    return project_runtime_root(scope.context) / "stop" / name


@contextmanager
def _locked(path: Path):
    if path.is_symlink():
        raise OSError("refusing symlink lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with suppress(OSError):
        path.parent.chmod(0o700)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(fd)
        raise OSError("continuation lock is not a private regular file")
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_json(path: Path, payload: dict[str, Any]) -> WriteResult:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_STATE_BYTES:
        raise OSError("continuation state exceeds its bounded limit")
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _safe_file(path, allow_missing=True)
        os.replace(temporary, path)
        _safe_file(path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return WriteResult(
            changed=True,
            bytes_written=len(encoded),
            files_written=(path.name,),
            replacements=1,
            fsync_publications=1,
        )
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def _load(path: Path) -> tuple[dict[str, Any], bool]:
    if not path.exists():
        return {"schema_version": STATE_SCHEMA_VERSION, "entries": {}}, False
    try:
        raw = _read_bounded(path, MAX_STATE_BYTES)
        if raw is None:
            raise ValueError("continuation state exceeds its bounded limit")
        data = json.loads(raw.decode("utf-8"))
    except (OSError, json.JSONDecodeError):
        invalid = path.with_name(f"{path.stem}.invalid.{int(_now())}.json")
        with suppress(OSError):
            os.replace(path, invalid)
        return {"schema_version": STATE_SCHEMA_VERSION, "entries": {}}, True
    if not isinstance(data, dict) or data.get("schema_version") != STATE_SCHEMA_VERSION or not isinstance(data.get("entries"), dict):
        invalid = path.with_name(f"{path.stem}.invalid.{int(_now())}.json")
        with suppress(OSError):
            os.replace(path, invalid)
        return {"schema_version": STATE_SCHEMA_VERSION, "entries": {}}, True
    return data, False


def _safe_file(path: Path, *, allow_missing: bool = False) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        if allow_missing:
            return None
        raise
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise OSError("continuation target is not a regular non-aliased file")
    return info


def _read_bounded(path: Path, max_bytes: int) -> bytes | None:
    before = _safe_file(path)
    if before is None or before.st_size > max_bytes:
        return None
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_size > max_bytes
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        ):
            return None
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(64 * 1024, max_bytes - total + 1))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                return None
        final = os.fstat(fd)
        if final.st_dev != opened.st_dev or final.st_ino != opened.st_ino or final.st_nlink != 1 or final.st_size != total:
            return None
        return b"".join(chunks)
    finally:
        os.close(fd)


def _trim(entries: dict[str, Any], now: float) -> dict[str, Any]:
    ttl = state_ttl_seconds()
    active = {
        key: value
        for key, value in entries.items()
        if isinstance(value, dict) and isinstance(value.get("timestamp"), (int, float)) and 0 <= now - float(value["timestamp"]) <= ttl
    }
    ordered = sorted(active.items(), key=lambda item: float(item[1].get("timestamp", 0)), reverse=True)
    return dict(ordered[: _max_entries()])


def _reserve_at(
    scope: StopScope,
    *,
    root: Path,
    path: Path,
    evidence_fingerprint: str,
    critical: bool,
) -> Reservation | None:
    lock = path.with_suffix(path.suffix + ".lock")
    if not all(_runtime_safe(candidate, root) for candidate in (root, path.parent, path, lock)):
        return None
    try:
        with _locked(lock):
            state, corrupt = _load(path)
            now = _now()
            entries = _trim(dict(state.get("entries", {})), now)
            current = entries.get(scope.scope_key)
            count = int(current.get("count", 0)) if isinstance(current, dict) else 0
            previous_fp = str(current.get("evidence_fingerprint", "")) if isinstance(current, dict) else ""
            allowed = count == 0 or (count == 1 and critical and evidence_fingerprint and evidence_fingerprint != previous_fp)
            next_count = count + 1 if allowed else count
            desired_entry = {
                "schema_version": SCHEMA_VERSION,
                "reason_code": "objective_gate",
                "evidence_fingerprint": evidence_fingerprint,
                "count": next_count,
                "timestamp": now,
                "project_id": scope.context.project_id,
                "session_id": scope.context.session_id,
                "task_signature": scope.task_signature,
                "branch": scope.context.branch,
                "sha": scope.context.sha,
            }
            current_semantic = {
                key: value
                for key, value in (current or {}).items()
                if key not in {"timestamp"}
            }
            desired_semantic = {
                key: value
                for key, value in desired_entry.items()
                if key not in {"timestamp"}
            }
            trimmed_changed = entries != dict(state.get("entries", {}))
            state_changed = corrupt or trimmed_changed or current_semantic != desired_semantic
            write_result = WriteResult()
            if state_changed:
                entries[scope.scope_key] = desired_entry
                write_result = _atomic_json(path, {"schema_version": STATE_SCHEMA_VERSION, "updated_at": now, "entries": entries})
            return Reservation(
                allowed,
                next_count,
                not allowed,
                evidence_fingerprint,
                corrupt,
                changed=state_changed,
                bytes_written=write_result.bytes_written,
                files_written=write_result.files_written,
                replacements=write_result.replacements,
                fsync_publications=write_result.fsync_publications,
            )
    except (OSError, ValueError, TypeError):
        return None


def reserve(scope: StopScope, *, evidence_fingerprint: str, critical: bool) -> Reservation:
    primary_root = ralph_home().expanduser()
    primary = _reserve_at(
        scope,
        root=primary_root,
        path=budget_path(scope),
        evidence_fingerprint=evidence_fingerprint,
        critical=critical,
    )
    if primary is not None:
        return primary
    fallback = fallback_budget_path(scope)
    if fallback is not None:
        fallback_root, fallback_path = fallback
        secondary = _reserve_at(
            scope,
            root=fallback_root,
            path=fallback_path,
            evidence_fingerprint=evidence_fingerprint,
            critical=critical,
        )
        if secondary is not None:
            return secondary
    # Preserve fail-open semantics when neither approved runtime can store a
    # loop counter, but distinguish the condition from a consumed budget.
    return Reservation(False, 0, False, evidence_fingerprint, storage_error=True)


def append_event(scope: StopScope, event: dict[str, Any], *, name: str = "stop-events.jsonl") -> WriteResult:
    path = events_path(scope, name)
    lock = path.with_suffix(path.suffix + ".lock")
    if not _runtime_safe(ralph_home()) or not _runtime_safe(path.parent) or not _runtime_safe(path) or not _runtime_safe(lock):
        return WriteResult.unknown()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with suppress(OSError):
            path.parent.chmod(0o700)
        with _locked(lock):
            encoded = (json.dumps(event, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")
            if len(encoded) > MAX_EVENT_RECORD_BYTES:
                return WriteResult.unknown()
            _safe_file(path, allow_missing=True)
            flags = os.O_CREAT | os.O_APPEND | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags, 0o600)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size + len(encoded) > MAX_EVENT_FILE_BYTES:
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
            with suppress(OSError):
                path.chmod(0o600)
        return WriteResult(changed=True, bytes_written=len(encoded), files_written=(path.name,), appends=1)
    except (OSError, TypeError, ValueError):
        return WriteResult.unknown()
