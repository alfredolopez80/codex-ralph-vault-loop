from __future__ import annotations

import json
import hashlib
import os
import stat
import tempfile
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .active_context import ActiveContext, project_runtime_root
from .checkpoint_io import CheckpointError, load_latest, semantic_fingerprint
from .continuation_budget import append_event
from .maintenance_queue import enqueue_maintenance
from .paths import _is_allowed_system_alias, ralph_home
from .persistence_metrics import WriteAccumulator, WriteResult
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
            if current.is_symlink() and not _is_allowed_system_alias(current):
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


TERMINAL_BUSINESS_SCHEMA_VERSION = 1
TERMINAL_BUSINESS_MAX_ENTRIES = 256


@dataclass
class TerminalBusinessClaim:
    """Lock-held terminal business dedupe claim.

    The marker stores only an opaque fingerprint.  It is deliberately
    separate from observability so a repeated successful Stop can remain
    physically read-only while safety gates still run on every invocation.
    """

    duplicate: bool
    fingerprint: str
    available: bool
    _commit_requested: bool = False
    write_result: WriteResult = WriteResult()

    def commit(self) -> None:
        if not self.duplicate and self.available:
            self._commit_requested = True


def _business_marker(scope: StopScope) -> Path:
    return project_runtime_root(scope.context) / "stop" / "terminal-business.json"


def _business_safe(path: Path) -> bool:
    root = ralph_home().expanduser()
    try:
        if root.is_symlink() or path.is_symlink():
            return False
        relative = path.relative_to(root)
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink() and not _is_allowed_system_alias(current):
                return False
            if current.is_file() and current.stat().st_nlink > 1:
                return False
        return True
    except (OSError, ValueError):
        return False


def _safe_runtime_bytes(path: Path, *, max_bytes: int, require_private: bool = True) -> bytes:
    """Read one runtime marker through a no-follow, bounded descriptor."""

    if not _business_safe(path):
        raise OSError("unsafe runtime marker path")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > max_bytes:
            raise OSError("unsafe runtime marker file")
        if require_private and info.st_mode & 0o077:
            raise OSError("runtime marker is not private")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(64 * 1024, max_bytes - total + 1))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise OSError("runtime marker exceeds its read limit")
        final = os.fstat(fd)
        if final.st_dev != info.st_dev or final.st_ino != info.st_ino or final.st_nlink != 1 or final.st_size != total:
            raise OSError("runtime marker changed during read")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _load_business(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    try:
        value = json.loads(_safe_runtime_bytes(path, max_bytes=128 * 1024).decode("utf-8"))
        if not isinstance(value, dict) or value.get("schema_version") != TERMINAL_BUSINESS_SCHEMA_VERSION:
            raise ValueError("incompatible terminal business state")
        entries = value.get("entries")
        if not isinstance(entries, dict):
            raise ValueError("invalid terminal business entries")
        result: dict[str, dict[str, str]] = {}
        for key, entry in entries.items():
            if not isinstance(key, str) or not isinstance(entry, dict):
                continue
            fingerprint = entry.get("fingerprint")
            if isinstance(fingerprint, str) and len(fingerprint) == 64:
                result[key[:128]] = {"fingerprint": fingerprint}
        return result
    except (OSError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        # A claim is a read boundary.  Malformed evidence stays in place for
        # explicit recovery; raising here makes the lock-held caller mark the
        # marker unavailable instead of treating it as an empty ledger and
        # atomically overwriting the forensic bytes on the next Stop.
        raise ValueError("terminal business marker is malformed") from exc


def _write_business(path: Path, entries: Mapping[str, Mapping[str, str]]) -> WriteResult:
    payload = {
        "schema_version": TERMINAL_BUSINESS_SCHEMA_VERSION,
        "entries": {key: dict(entries[key]) for key in sorted(entries)[-TERMINAL_BUSINESS_MAX_ENTRIES:]},
    }
    encoded = (json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("utf-8")
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        if not _business_safe(path):
            raise OSError("unsafe terminal business target")
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if not _business_safe(path):
            raise OSError("terminal business target changed during publication")
        fd_dir = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(fd_dir)
        finally:
            os.close(fd_dir)
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


@contextmanager
def terminal_business_claim(scope: StopScope, fingerprint: str):
    """Serialize the terminal business decision for one scoped task."""
    marker = _business_marker(scope)
    lock_path = marker.with_suffix(".lock")
    if not _business_safe(marker) or not _business_safe(lock_path):
        yield TerminalBusinessClaim(False, fingerprint, False)
        return
    try:
        marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with suppress(OSError):
            marker.parent.chmod(0o700)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            os.close(fd)
            raise OSError("unsafe terminal business lock")
        os.fchmod(fd, 0o600)
        lock = os.fdopen(fd, "a+", encoding="utf-8")
    except (OSError, TypeError, ValueError):
        yield TerminalBusinessClaim(False, fingerprint, False, write_result=WriteResult.unknown())
        return
    try:
        if not _business_safe(marker) or not _business_safe(lock_path):
            lock.close()
            yield TerminalBusinessClaim(False, fingerprint, False)
            return
        if fcntl is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        entries = _load_business(marker)
        current = entries.get(scope.scope_key, {})
        claim = TerminalBusinessClaim(current.get("fingerprint") == fingerprint, fingerprint, True)
    except (OSError, TypeError, ValueError):
        lock.close()
        yield TerminalBusinessClaim(False, fingerprint, False, write_result=WriteResult.unknown())
        return

    try:
        yield claim
        if claim._commit_requested:
            entries[scope.scope_key] = {"fingerprint": fingerprint}
            try:
                claim.write_result = _write_business(marker, entries)
            except (OSError, TypeError, ValueError):
                claim.write_result = WriteResult.unknown(changed=True)
    finally:
        if fcntl is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def _hashed_material(value: object, *, depth: int = 0) -> object:
    """Normalize selected gate metadata without retaining raw strings."""
    if depth > 3:
        return "depth-limited"
    if isinstance(value, str):
        return {"sha256": hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest(), "length": len(value)}
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key)[:64]: _hashed_material(item, depth=depth + 1)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))[:32]
        }
    if isinstance(value, (list, tuple, set)):
        return [_hashed_material(item, depth=depth + 1) for item in list(value)[:32]]
    return type(value).__name__


def terminal_business_fingerprint(
    payload: Mapping[str, object],
    scope: StopScope,
    findings: list[object],
    *,
    gate_reports: tuple[str, ...] = (),
) -> str:
    """Hash scoped terminal meaning, excluding telemetry timestamps/content."""
    checkpoint: Mapping[str, object] = {}
    try:
        loaded = load_latest(context=scope.context)
        if isinstance(loaded, Mapping):
            checkpoint = loaded
    except (CheckpointError, OSError, ValueError):
        checkpoint = {}
    generation_keys = ("memory_generation", "memoryGeneration", "source_generation", "generation", "checkpoint_generation")
    generation = [payload.get(key) for key in generation_keys if payload.get(key) not in (None, "")]
    plan_keys = ("implementation_plan_path", "implementationPlanPath", "plan_path", "planPath", "plan_id", "planId")
    plan = [payload.get(key) for key in plan_keys if payload.get(key) not in (None, "")]
    validation_keys = (
        "validation_status",
        "validationStatus",
        "tests_failed",
        "testsFailed",
        "tests_passed",
        "testsPassed",
        "lint_failed",
        "build_failed",
        "typecheck_failed",
        "verified_done",
        "verifiedDone",
        "objective_state",
        "quality_state",
        "plan_state",
        "checkpoint_state",
    )
    validation = {key: payload.get(key) for key in validation_keys if key in payload}
    finding_material = [
        {
            "code": getattr(finding, "code", ""),
            "critical": bool(getattr(finding, "critical", False)),
            "fingerprint": getattr(finding, "fingerprint", "") or getattr(finding, "code", ""),
        }
        for finding in findings
    ]
    material = {
        "schema_version": TERMINAL_BUSINESS_SCHEMA_VERSION,
        "scope": {
            "project_id": scope.context.project_id,
            "workspace_instance_id": scope.context.workspace_instance_id,
            "session_id": scope.context.session_id,
            "branch": scope.context.branch,
            "sha": scope.context.sha,
            "task_signature": scope.task_signature,
        },
        "terminal_state": "blocked" if findings else "complete",
        "findings": sorted(finding_material, key=lambda item: (item["code"], item["fingerprint"])),
        "gate_reports": sorted(set(str(item) for item in gate_reports))[:16],
        "generation": _hashed_material(generation),
        "plan_identity": _hashed_material(plan),
        "validation": _hashed_material(validation),
        "checkpoint_semantic": semantic_fingerprint(checkpoint) if checkpoint else "missing",
        "learning_candidate": _hashed_material(payload.get("learning_candidate")),
    }
    encoded = json.dumps(material, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
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


def _handoff_marker(scope: StopScope) -> Path:
    return project_runtime_root(scope.context) / "stop" / "handoff-dedupe.json"


def _marker_value(path: Path) -> str:
    try:
        data = json.loads(_safe_runtime_bytes(path, max_bytes=8 * 1024).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
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
        "checkpoint_semantic": semantic_fingerprint(checkpoint) if checkpoint else "",
        "selected_memory_ids": safe_selected,
        "memory_generation": str(payload.get("memory_generation") or payload.get("memoryGeneration") or "")[:96],
        "recall_status": str(payload.get("recall_status") or "")[:32],
    }
    encoded = json.dumps(material, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


def _write_marker(path: Path, scope: StopScope, fingerprint: str) -> WriteResult:
    if not _business_safe(path):
        raise OSError("refusing unsafe handoff marker")
    payload = {"schema_version": 2, "scope_key": scope.scope_key, "fingerprint": fingerprint}
    encoded = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if not _business_safe(path):
            raise OSError("handoff marker changed during publication")
        fd_dir = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(fd_dir)
        finally:
            os.close(fd_dir)
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


def persist_event(scope: StopScope, *, event: str, reason_codes: list[str] | tuple[str, ...] = (), runtime_ms: float = 0.0, continuation_count: int = 0, output_bytes: int = 0, persisted_bytes: int | None = 0) -> WriteResult:
    if not _safe_runtime(scope):
        return WriteResult.unknown()
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
        "persisted_bytes": max(0, persisted_bytes) if persisted_bytes is not None else None,
    }
    return append_event(scope, payload)


def mark_promotion_pending(scope: StopScope, payload: Mapping[str, object]) -> WriteResult:
    if not _safe_runtime(scope):
        return WriteResult.unknown()
    # Stop owns only the durable marker/enqueue.  Dream and vault review run
    # later through scripts/memory/run-pending-maintenance.py.
    enqueue_result = enqueue_maintenance(scope.context, reason_code="stop", payload=payload)
    accounting = WriteAccumulator()
    accounting.add(getattr(enqueue_result, "write_result", None))
    selected = payload.get("selected_memory_ids") or payload.get("selectedMemoryIds")
    candidates = payload.get("memory_candidates") or payload.get("memoryCandidates")
    promotion_required = bool(candidates or selected or payload.get("learning_candidate"))
    if not promotion_required:
        return accounting.result(changed=bool(enqueue_result.accepted) or accounting.bytes_written not in (0, None))
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
    accounting.add(append_event(scope, event, name="promotion-pending.jsonl"))
    return accounting.result(changed=accounting.bytes_written not in (0, None) or bool(enqueue_result.accepted))


def persist_handoff(payload: Mapping[str, object], context: ActiveContext, scope: StopScope) -> WriteResult:
    if not _safe_runtime(scope):
        return WriteResult.unknown()
    try:
        from stop_persist_memory import run as persist_stop_handoff

        marker = _handoff_marker(scope)
        fingerprint = _handoff_fingerprint(payload, scope)
        with _handoff_lock(scope) as locked:
            if not locked:
                return WriteResult.unknown()
            if _marker_value(marker) == fingerprint:
                return WriteResult()
            handoff_result = persist_stop_handoff(dict(payload), context=context)
            if not handoff_result:
                return handoff_result
            marker_result = _write_marker(marker, scope, fingerprint)
            accounting = WriteAccumulator()
            accounting.add(handoff_result)
            accounting.add(marker_result)
            return accounting.result(changed=True)
    except (OSError, ValueError, RuntimeError):
        return WriteResult.unknown()
