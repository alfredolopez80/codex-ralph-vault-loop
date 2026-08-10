"""Private, content-free cache for UserPromptSubmit context fingerprints."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import stat
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]
from .active_context import ActiveContext, project_runtime_root
from .paths import now_iso, ralph_home
from .task_signature import TaskSignature
SCHEMA_VERSION = 1
CONTRACT_VERSION = "prompt-context-v1"
DEFAULT_TTL_SECONDS = 300
DEFAULT_MAX_ENTRIES = 128
DEFAULT_INFLIGHT_SECONDS = 15
MAX_STATE_BYTES = 512 * 1024
@dataclass(frozen=True)
class CacheClaim:
    status: str
    invalidation_reason: str
    selected_memory_ids: tuple[str, ...] = ()
    fingerprint: str = ""
    changed: bool = False
    bytes_written: int = 0
    files_written: tuple[str, ...] = ()


@dataclass(frozen=True)
class CacheWriteResult:
    """Content-free publication metadata for cache writers.

    The result is intentionally not stored in the cache.  ``__bool__`` keeps
    the historical truthiness contract for callers that only need to know
    whether a publication succeeded.
    """

    changed: bool = False
    bytes_written: int = 0
    files_written: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.changed


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def ttl_seconds() -> int:
    return _int_env("RALPH_CONTEXT_CACHE_TTL_SECONDS", DEFAULT_TTL_SECONDS, 1, 24 * 60 * 60)


def max_entries() -> int:
    return _int_env("RALPH_CONTEXT_CACHE_MAX_ENTRIES", DEFAULT_MAX_ENTRIES, 1, 2048)


def _safe_id(value: object, limit: int = 96) -> str:
    text = str(value or "")
    return "".join(char for char in text if char.isalnum() or char in "._:-")[:limit]


def _session_key(context: ActiveContext) -> str:
    return hashlib.sha256(context.session_id.encode("utf-8", errors="replace")).hexdigest()[:24]


def cache_path(context: ActiveContext) -> Path:
    return project_runtime_root(context) / "prompt-context" / "cache.json"


def _safe_under(root: Path, path: Path) -> bool:
    try:
        root = root.expanduser()
        if not root.is_absolute() or root.is_symlink() or path.is_symlink():
            return False
        relative = path.relative_to(root)
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return False
        return True
    except (OSError, ValueError):
        return False


def _ensure_private(root: Path, parent: Path) -> None:
    relative = parent.relative_to(root)
    current = root
    if current.is_symlink():
        raise OSError("refusing symlink runtime root")
    current.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        current.chmod(0o700)
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise OSError("refusing symlink cache path")
        current.mkdir(exist_ok=True)
        with contextlib.suppress(OSError):
            current.chmod(0o700)


@contextmanager
def _locked(context: ActiveContext) -> Iterator[bool]:
    root = ralph_home().expanduser()
    path = cache_path(context)
    lock = path.with_suffix(".lock")
    if not all(_safe_under(root, candidate) for candidate in (path.parent, path, lock)):
        yield False
        return
    try:
        _ensure_private(root, path.parent)
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(lock, flags, 0o600)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            os.close(fd)
            yield False
            return
        os.fchmod(fd, 0o600)
        handle = os.fdopen(fd, "a+", encoding="utf-8")
    except OSError:
        yield False
        return
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield True
    finally:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _empty() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "updated_at": now_iso(), "entries": {}}


def _quarantine(path: Path) -> None:
    if not path.exists() or path.is_symlink():
        return
    target = path.with_name(f"{path.stem}.invalid.{int(time.time())}.json")
    with contextlib.suppress(OSError):
        os.replace(path, target)


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _empty()
    try:
        raw = _read_bounded(path, MAX_STATE_BYTES)
        if raw is None:
            _quarantine(path)
            return _empty()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _quarantine(path)
        return _empty()
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION or not isinstance(data.get("entries"), dict):
        _quarantine(path)
        return _empty()
    return data


def _prune(entries: Mapping[str, object], now: float) -> dict[str, dict[str, Any]]:
    kept: list[tuple[str, dict[str, Any]]] = []
    ttl = ttl_seconds()
    for key, value in entries.items():
        if not isinstance(value, dict):
            continue
        try:
            updated = float(value.get("updated_epoch", 0))
        except (TypeError, ValueError):
            continue
        if updated and 0 <= now - updated <= ttl:
            kept.append((str(key), dict(value)))
    kept.sort(key=lambda item: float(item[1].get("updated_epoch", 0)), reverse=True)
    return dict(kept[: max_entries()])


def _write(path: Path, entries: Mapping[str, object]) -> bool:
    payload = {"schema_version": SCHEMA_VERSION, "updated_at": now_iso(), "entries": entries}
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    if len(encoded.encode("utf-8")) > MAX_STATE_BYTES:
        return False
    try:
        fd, name = tempfile.mkstemp(prefix=".cache.", suffix=".tmp", dir=path.parent)
        temporary = Path(name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(encoded)
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
        finally:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()
        return True
    except OSError:
        return False


def _safe_file(path: Path, *, allow_missing: bool = False) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        if allow_missing:
            return None
        raise
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise OSError("prompt context cache target is not a regular non-aliased file")
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


def context_fingerprint(
    signature: TaskSignature,
    *,
    selected_memory_ids: Sequence[str],
    memory_generation: str,
    route: str,
    profile: str,
    clarification_state: str,
    checkpoint_hash: str,
) -> str:
    material = {
        "contract_version": CONTRACT_VERSION,
        "task_signature": signature.value,
        "selected_memory_ids": sorted(_safe_id(item) for item in selected_memory_ids if _safe_id(item))[:8],
        "memory_generation": _safe_id(memory_generation),
        "route": _safe_id(route),
        "profile": _safe_id(profile),
        "clarification_state": _safe_id(clarification_state),
        "checkpoint_hash": _safe_id(checkpoint_hash),
    }
    encoded = json.dumps(material, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


def claim(
    context: ActiveContext,
    signature: TaskSignature,
    *,
    memory_generation: str,
    route: str,
    profile: str,
    clarification_state: str,
    checkpoint_hash: str,
) -> CacheClaim:
    path = cache_path(context)
    with _locked(context) as locked:
        if not locked:
            return CacheClaim("unavailable", "cache_unavailable")
        now = time.time()
        state = _load(path)
        raw_entries = state.get("entries", {})
        entries = _prune(raw_entries, now)
        key = f"{_session_key(context)}:{signature.value}"
        current = entries.get(key)
        if isinstance(current, dict):
            selected = tuple(_safe_id(item) for item in current.get("selected_memory_ids", []) if _safe_id(item))
            effective_clarification = clarification_state
            if effective_clarification in {"", "unknown"}:
                effective_clarification = str(current.get("clarification_state") or "unknown")
            expected = context_fingerprint(
                signature,
                selected_memory_ids=selected,
                memory_generation=memory_generation,
                route=route,
                profile=profile,
                clarification_state=effective_clarification,
                checkpoint_hash=checkpoint_hash,
            )
            if current.get("status") == "ready" and current.get("fingerprint") == expected:
                # A valid hit is a read-only operation.  Pruning other entries
                # is the only permitted amortized maintenance publication.
                changed = False
                bytes_written = 0
                files_written: tuple[str, ...] = ()
                if entries != raw_entries:
                    changed = _write(path, entries)
                    if changed:
                        with contextlib.suppress(OSError):
                            bytes_written = path.stat().st_size
                        files_written = ("cache.json",)
                return CacheClaim(
                    "hit",
                    "unchanged",
                    selected,
                    expected,
                    changed=changed,
                    bytes_written=bytes_written,
                    files_written=files_written,
                )
            if current.get("status") == "inflight" and now - float(current.get("updated_epoch", 0)) <= DEFAULT_INFLIGHT_SECONDS:
                return CacheClaim("inflight", "concurrent_claim")
            reason = "context_fingerprint_changed"
        else:
            reason = "new_task_signature"
        entries[key] = {
            "schema_version": SCHEMA_VERSION,
            "contract_version": CONTRACT_VERSION,
            "status": "inflight",
            "task_signature": signature.value,
            "task_anchor": signature.anchor,
            "project_id": signature.project_id,
            "workspace_instance_id": signature.workspace_instance_id,
            "branch": signature.branch,
            "head": signature.head,
            "prompt_hash": signature.prompt_hash,
            "intent": signature.intent,
            "sensitivity": signature.sensitivity,
            "model_family": signature.model_family,
            "model_source": signature.model_source,
            "model_verified": signature.model_verified,
            "checkpoint_identity": signature.checkpoint_identity,
            "selected_memory_ids": [],
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "updated_epoch": now,
        }
        if not _write(path, entries):
            return CacheClaim("unavailable", "cache_write_failed")
        bytes_written = 0
        with contextlib.suppress(OSError):
            bytes_written = path.stat().st_size
        return CacheClaim("miss", reason, changed=True, bytes_written=bytes_written, files_written=("cache.json",))


def finalize(
    context: ActiveContext,
    signature: TaskSignature,
    *,
    selected_memory_ids: Sequence[str],
    memory_generation: str,
    route: str,
    profile: str,
    clarification_state: str,
    checkpoint_hash: str,
) -> CacheWriteResult:
    path = cache_path(context)
    with _locked(context) as locked:
        if not locked:
            return CacheWriteResult()
        now = time.time()
        state = _load(path)
        entries = _prune(state.get("entries", {}), now)
        key = f"{_session_key(context)}:{signature.value}"
        current = entries.get(key)
        if not isinstance(current, dict) or current.get("status") != "inflight":
            return CacheWriteResult()
        selected = sorted({_safe_id(item) for item in selected_memory_ids if _safe_id(item)})[:8]
        fingerprint = context_fingerprint(
            signature,
            selected_memory_ids=selected,
            memory_generation=memory_generation,
            route=route,
            profile=profile,
            clarification_state=clarification_state,
            checkpoint_hash=checkpoint_hash,
        )
        current.update(
            {
                "status": "ready",
                "selected_memory_ids": selected,
                "memory_generation": _safe_id(memory_generation),
                "route": _safe_id(route),
                "profile": _safe_id(profile),
                "clarification_state": _safe_id(clarification_state),
                "checkpoint_hash": _safe_id(checkpoint_hash),
                "fingerprint": fingerprint,
                "updated_at": now_iso(),
                "updated_epoch": now,
            }
        )
        entries[key] = current
        if not _write(path, entries):
            return CacheWriteResult()
        bytes_written = 0
        with contextlib.suppress(OSError):
            bytes_written = path.stat().st_size
        return CacheWriteResult(changed=True, bytes_written=bytes_written, files_written=("cache.json",))


def discard(context: ActiveContext, signature: TaskSignature) -> CacheWriteResult:
    path = cache_path(context)
    with _locked(context) as locked:
        if not locked:
            return CacheWriteResult()
        state = _load(path)
        entries = dict(state.get("entries", {})) if isinstance(state.get("entries"), dict) else {}
        entries.pop(f"{_session_key(context)}:{signature.value}", None)
        if not _write(path, _prune(entries, time.time())):
            return CacheWriteResult()
        bytes_written = 0
        with contextlib.suppress(OSError):
            bytes_written = path.stat().st_size
        return CacheWriteResult(changed=True, bytes_written=bytes_written, files_written=("cache.json",))


__all__ = [
    "CONTRACT_VERSION", "CacheClaim", "CacheWriteResult", "cache_path", "claim", "context_fingerprint", "discard", "finalize",
    "max_entries", "ttl_seconds",
]
