from __future__ import annotations

import json
import hashlib
import os
import tempfile
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .active_context import ActiveContext, project_runtime_root
from .checkpoint_io import CheckpointError, load_latest
from .continuation_budget import append_event
from .maintenance_queue import enqueue_maintenance
from .paths import ralph_home
from .stop_scope import StopScope

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_runtime(scope: StopScope) -> bool:
    root = ralph_home()
    target = project_runtime_root(scope.context) / "stop"
    try:
        if root.is_symlink():
            return False
        relative = target.relative_to(root)
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return False
        return True
    except OSError:
        return False


def _count(value: object) -> int:
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    if isinstance(value, int):
        return max(0, value)
    return 0


@contextmanager
def _handoff_lock(scope: StopScope):
    lock_path = project_runtime_root(scope.context) / "stop" / "handoff.lock"
    try:
        if lock_path.is_symlink():
            yield False
            return
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with suppress(OSError):
            lock_path.parent.chmod(0o700)
        handle = lock_path.open("a+", encoding="utf-8")
        with suppress(OSError):
            lock_path.chmod(0o600)
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


def _handoff_marker(scope: StopScope) -> Path:
    return project_runtime_root(scope.context) / "stop" / "handoff-dedupe.json"


def _marker_value(path: Path) -> str:
    if path.is_symlink():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(data.get("fingerprint", "")) if isinstance(data, dict) else ""


def _handoff_fingerprint(payload: Mapping[str, object], scope: StopScope) -> str:
    checkpoint: Mapping[str, object] = {}
    try:
        loaded = load_latest(context=scope.context)
        if isinstance(loaded, Mapping):
            checkpoint = loaded
    except (CheckpointError, OSError, ValueError):
        checkpoint = {}
    selected = payload.get("selected_memory_ids") or payload.get("selectedMemoryIds")
    safe_selected = sorted(str(item)[:96] for item in selected if isinstance(item, str))[:8] if isinstance(selected, list) else []
    material = {
        "scope_key": scope.scope_key,
        "turn_id": scope.turn_id,
        "checkpoint_hash": str(checkpoint.get("content_hash") or "")[:96],
        "checkpoint_updated_at": str(checkpoint.get("updated_at") or "")[:64],
        "selected_memory_ids": safe_selected,
        "memory_generation": str(payload.get("memory_generation") or payload.get("memoryGeneration") or "")[:96],
        "recall_status": str(payload.get("recall_status") or "")[:32],
    }
    encoded = json.dumps(material, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


def _write_marker(path: Path, scope: StopScope, fingerprint: str) -> None:
    if path.is_symlink():
        raise OSError("refusing symlink handoff marker")
    payload = {"schema_version": 2, "scope_key": scope.scope_key, "fingerprint": fingerprint, "updated_at": _now()}
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def persist_event(scope: StopScope, *, event: str, reason_codes: list[str] | tuple[str, ...] = (), runtime_ms: float = 0.0, continuation_count: int = 0, output_bytes: int = 0, persisted_bytes: int = 0) -> bool:
    if not _safe_runtime(scope):
        return False
    payload = {
        "schema_version": 1,
        "created_at": _now(),
        "event": event,
        "project_id": scope.context.project_id,
        "session_id": scope.context.session_id,
        "task_signature": scope.task_signature,
        "branch": scope.context.branch,
        "sha": scope.context.sha,
        "reason_codes": sorted(set(str(code) for code in reason_codes))[:12],
        "runtime_ms": round(max(0.0, runtime_ms), 3),
        "continuation_count": max(0, continuation_count),
        "output_bytes": max(0, output_bytes),
        "persisted_bytes": max(0, persisted_bytes),
    }
    return append_event(scope, payload)


def mark_promotion_pending(scope: StopScope, payload: Mapping[str, object]) -> bool:
    if not _safe_runtime(scope):
        return False
    # Stop owns only the durable marker/enqueue.  Dream and vault review run
    # later through scripts/memory/run-pending-maintenance.py.
    enqueue_maintenance(scope.context, reason_code="stop", payload=payload)
    selected = payload.get("selected_memory_ids") or payload.get("selectedMemoryIds")
    candidates = payload.get("memory_candidates") or payload.get("memoryCandidates")
    promotion_required = bool(candidates or selected or payload.get("learning_candidate"))
    if not promotion_required:
        return False
    event = {
        "schema_version": 1,
        "created_at": _now(),
        "event": "promotion_deferred",
        "project_id": scope.context.project_id,
        "session_id": scope.context.session_id,
        "task_signature": scope.task_signature,
        "candidate_count": _count(candidates) or _count(selected),
        "promotion_required": promotion_required,
        "heavy_promotion": "deferred",
    }
    return append_event(scope, event, name="promotion-pending.jsonl")


def persist_handoff(payload: Mapping[str, object], context: ActiveContext, scope: StopScope) -> bool:
    if not _safe_runtime(scope):
        return False
    try:
        from stop_persist_memory import run as persist_stop_handoff

        marker = _handoff_marker(scope)
        fingerprint = _handoff_fingerprint(payload, scope)
        with _handoff_lock(scope) as locked:
            if not locked:
                return False
            if _marker_value(marker) == fingerprint:
                return True
            persisted = bool(persist_stop_handoff(dict(payload), context=context))
            if persisted:
                _write_marker(marker, scope, fingerprint)
            return persisted
    except (OSError, ValueError, RuntimeError):
        return False
