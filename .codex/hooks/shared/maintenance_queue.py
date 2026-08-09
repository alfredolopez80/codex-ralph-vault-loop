"""Small, descriptor-only queue for deferred Ralph memory maintenance.

Interactive hooks only append an idempotent job descriptor.  The queue is
intentionally boring: one locked JSON file per project, atomic replacement,
bounded retention, and fail-open behaviour for local runtime failures.  No
prompt, memory body, tool output, or vault content is ever accepted here.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping

from .active_context import ActiveContext, active_context_from_payload
from .paths import now_iso, ralph_home

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


SCHEMA_VERSION = 1
OPERATION = "dream_and_vault_review"
DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60
DEFAULT_DEBOUNCE_SECONDS = 60
DEFAULT_MAX_ENTRIES = 256
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_LEASE_SECONDS = 30
MAX_EVENT_BYTES = 128 * 1024
MAX_EVENT_LINES = 512


@dataclass(frozen=True)
class EnqueueResult:
    accepted: bool
    deduplicated: bool
    job_id: str
    reason: str
    path: Path | None = None


@dataclass(frozen=True)
class MaintenanceJob:
    job_id: str
    operation: str
    project_id: str
    project_slug: str
    workspace_root: str
    workspace_instance_id: str
    session_id: str
    branch: str
    sha: str
    source_generation: str
    reason_code: str
    policy_version: str
    created_at: str
    updated_at: str
    status: str
    attempts: int
    max_attempts: int
    next_attempt_at: float
    lease_until: float
    last_error_code: str


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def queue_ttl_seconds() -> int:
    return _int_env("RALPH_MAINTENANCE_TTL_SECONDS", DEFAULT_TTL_SECONDS, 1, 30 * 24 * 60 * 60)


def debounce_seconds() -> int:
    return _int_env("RALPH_MAINTENANCE_DEBOUNCE_SECONDS", DEFAULT_DEBOUNCE_SECONDS, 0, 24 * 60 * 60)


def max_entries() -> int:
    return _int_env("RALPH_MAINTENANCE_MAX_ENTRIES", DEFAULT_MAX_ENTRIES, 1, 4096)


def max_attempts() -> int:
    return _int_env("RALPH_MAINTENANCE_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS, 1, 8)


def lease_seconds() -> int:
    return _int_env("RALPH_MAINTENANCE_LEASE_SECONDS", DEFAULT_LEASE_SECONDS, 1, 15 * 60)


def _epoch() -> float:
    return time.time()


def _safe_component(value: object, *, limit: int = 160) -> str:
    text = str(value or "")
    return "".join(char if char.isalnum() or char in "._-:/" else "_" for char in text)[:limit]


def _safe_identifier(value: object, *, limit: int = 80) -> str:
    text = str(value or "")
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in text)[:limit] or "unknown"


def _safe_runtime(path: Path) -> bool:
    """Reject symlink traversal below the configured Ralph runtime root."""
    try:
        root = ralph_home().expanduser()
        if root.is_symlink() or path.is_symlink():
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


def _ensure_private_dirs(path: Path) -> None:
    root = ralph_home().expanduser()
    relative_parent = path.parent.relative_to(root)
    current = root
    if current.is_symlink():
        raise OSError("refusing symlink runtime root")
    current.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        current.chmod(0o700)
    for part in relative_parent.parts:
        current = current / part
        if current.is_symlink():
            raise OSError("refusing symlink runtime directory")
        current.mkdir(exist_ok=True)
        with contextlib.suppress(OSError):
            current.chmod(0o700)


def queue_path(project_id: str) -> Path:
    return ralph_home() / "projects" / _safe_identifier(project_id) / "maintenance" / "queue.json"


def event_path(project_id: str) -> Path:
    return queue_path(project_id).with_name("runner-events.jsonl")


def runner_lock_path() -> Path:
    return ralph_home() / "maintenance" / "runner.lock"


@contextmanager
def _locked(path: Path) -> Iterator[bool]:
    try:
        if not _safe_runtime(path):
            yield False
            return
        _ensure_private_dirs(path)
        handle = path.open("a+", encoding="utf-8")
        with contextlib.suppress(OSError):
            path.chmod(0o600)
    except (OSError, ValueError):
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


@contextmanager
def instance_lock() -> Iterator[bool]:
    """Serialize runner instances without creating a daemon or child process."""
    with _locked(runner_lock_path()) as locked:
        yield locked


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        with contextlib.suppress(OSError):
            path.chmod(0o600)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _quarantine(path: Path) -> None:
    if not path.exists() or path.is_symlink():
        return
    target = path.with_name(f"{path.stem}.invalid.{int(_epoch())}.json")
    with contextlib.suppress(OSError):
        os.replace(path, target)


def _empty_state() -> dict[str, object]:
    return {"schema_version": SCHEMA_VERSION, "updated_at": now_iso(), "jobs": []}


def _load(path: Path) -> dict[str, object]:
    if not path.exists():
        return _empty_state()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _quarantine(path)
        return _empty_state()
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION or not isinstance(value.get("jobs"), list):
        _quarantine(path)
        return _empty_state()
    return value


def _timestamp(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _trim_jobs(raw_jobs: object, now: float) -> list[dict[str, object]]:
    if not isinstance(raw_jobs, list):
        return []
    jobs: list[dict[str, object]] = []
    ttl = queue_ttl_seconds()
    for raw in raw_jobs:
        if not isinstance(raw, dict):
            continue
        created = _timestamp(raw.get("created_epoch"))
        updated = _timestamp(raw.get("updated_epoch")) or created
        if not created or now - max(created, updated) > ttl:
            continue
        job = dict(raw)
        if job.get("status") == "leased" and _timestamp(job.get("lease_until")) <= now:
            attempts = max(0, int(job.get("attempts", 0) or 0))
            maximum = max(1, int(job.get("max_attempts", DEFAULT_MAX_ATTEMPTS) or DEFAULT_MAX_ATTEMPTS))
            job["status"] = "dead_lettered" if attempts >= maximum else "retryable"
            job["next_attempt_at"] = 0.0 if attempts >= maximum else now
            job["lease_until"] = 0.0
            if attempts >= maximum:
                job["last_error_code"] = "lease_attempts_exhausted"
        jobs.append(job)
    jobs.sort(key=lambda item: _timestamp(item.get("updated_epoch")), reverse=True)
    return jobs[: max_entries()]


def _source_generation(context: ActiveContext, payload: Mapping[str, object] | None) -> str:
    """Return a hash of metadata/statistics only; never hash or store raw content."""
    payload = payload or {}
    explicit = payload.get("memory_generation") or payload.get("memoryGeneration") or payload.get("source_generation")
    if isinstance(explicit, str) and explicit.strip():
        return hashlib.sha256(explicit.strip()[:256].encode("utf-8")).hexdigest()[:24]
    root = ralph_home() / "projects" / _safe_identifier(context.project_id)
    material: list[str] = []
    for relative in ("handoffs/latest.md", "ledgers/learning-events.jsonl"):
        path = root / relative
        try:
            stat = path.stat()
            material.append(f"{relative}:{stat.st_mtime_ns}:{stat.st_size}")
        except OSError:
            material.append(f"{relative}:missing")
    return hashlib.sha256("|".join(material).encode("utf-8")).hexdigest()[:24]


def _job_id(*, context: ActiveContext, source_generation: str, policy_version: str) -> str:
    material = "|".join(
        (
            OPERATION,
            context.project_id,
            context.workspace_instance_id,
            context.branch,
            context.sha,
            source_generation,
            policy_version,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _descriptor(context: ActiveContext, *, reason_code: str, payload: Mapping[str, object] | None) -> dict[str, object]:
    policy = _safe_component(os.environ.get("RALPH_MAINTENANCE_POLICY_VERSION", "maintenance-v1"), limit=64)
    generation = _source_generation(context, payload)
    now = _epoch()
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": _job_id(context=context, source_generation=generation, policy_version=policy),
        "operation": OPERATION,
        "project_id": _safe_identifier(context.project_id),
        "project_slug": _safe_identifier(context.project_slug),
        # The workspace path is metadata needed by the explicit runner.  It is
        # not content and is bounded to keep queue records small.
        "workspace_root": str(context.workspace_root)[:240],
        "workspace_instance_id": _safe_component(context.workspace_instance_id, limit=64),
        "session_id": _safe_component(context.session_id, limit=80),
        "branch": _safe_component(context.branch, limit=160),
        "sha": _safe_component(context.sha, limit=80),
        "source_generation": generation,
        "reason_code": _safe_component(reason_code, limit=64) or "interactive_hook",
        "policy_version": policy,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_epoch": now,
        "updated_epoch": now,
        "status": "pending",
        "attempts": 0,
        "max_attempts": max_attempts(),
        "next_attempt_at": now,
        "lease_until": 0.0,
        "last_error_code": "",
    }


def enqueue_maintenance(context: ActiveContext, *, reason_code: str = "interactive_hook", payload: Mapping[str, object] | None = None) -> EnqueueResult:
    """Best-effort idempotent enqueue; errors never become hook failures."""
    path = queue_path(context.project_id)
    job = _descriptor(context, reason_code=reason_code, payload=payload)
    lock_path = path.with_suffix(path.suffix + ".lock")
    if not _safe_runtime(path) or not _safe_runtime(lock_path):
        return EnqueueResult(False, False, str(job["job_id"]), "unsafe_runtime", None)
    try:
        with _locked(lock_path) as locked:
            if not locked:
                return EnqueueResult(False, False, str(job["job_id"]), "lock_unavailable", path)
            state = _load(path)
            now = _epoch()
            jobs = _trim_jobs(state.get("jobs"), now)
            job_id = str(job["job_id"])
            existing = next((item for item in jobs if str(item.get("job_id")) == job_id), None)
            if existing is not None:
                status = str(existing.get("status") or "pending")
                if status in {"pending", "leased", "retryable", "completed", "dead_lettered"}:
                    return EnqueueResult(False, True, job_id, f"already_{status}", path)
            # A handoff can update file metadata on every Stop.  Debounce
            # those equivalent observations before creating another job.
            recent_cutoff = now - debounce_seconds()
            for item in jobs:
                if (
                    str(item.get("operation")) == OPERATION
                    and str(item.get("project_id")) == str(job.get("project_id"))
                    and str(item.get("workspace_instance_id")) == str(job.get("workspace_instance_id"))
                    and str(item.get("branch")) == str(job.get("branch"))
                    and str(item.get("sha")) == str(job.get("sha"))
                    and str(item.get("source_generation")) == str(job.get("source_generation"))
                    and str(item.get("policy_version")) == str(job.get("policy_version"))
                    and _timestamp(item.get("created_epoch")) >= recent_cutoff
                ):
                    return EnqueueResult(False, True, str(item.get("job_id") or job_id), "debounced", path)
            jobs.append(job)
            _atomic_json(path, {"schema_version": SCHEMA_VERSION, "updated_at": now_iso(), "jobs": _trim_jobs(jobs, now)})
            return EnqueueResult(True, False, job_id, "enqueued", path)
    except (OSError, TypeError, ValueError):
        return EnqueueResult(False, False, str(job["job_id"]), "queue_write_failed", path)


def enqueue_for_payload(payload: Mapping[str, object], *, reason_code: str) -> EnqueueResult:
    try:
        context = active_context_from_payload(dict(payload))
        return enqueue_maintenance(context, reason_code=reason_code, payload=payload)
    except Exception:
        return EnqueueResult(False, False, "", "context_failed", None)


def _job_from_dict(raw: Mapping[str, object]) -> MaintenanceJob | None:
    try:
        return MaintenanceJob(
            job_id=str(raw["job_id"]), operation=str(raw["operation"]), project_id=str(raw["project_id"]),
            project_slug=str(raw.get("project_slug") or ""), workspace_root=str(raw.get("workspace_root") or ""),
            workspace_instance_id=str(raw.get("workspace_instance_id") or ""), session_id=str(raw.get("session_id") or ""),
            branch=str(raw.get("branch") or ""), sha=str(raw.get("sha") or ""), source_generation=str(raw.get("source_generation") or ""),
            reason_code=str(raw.get("reason_code") or ""), policy_version=str(raw.get("policy_version") or ""),
            created_at=str(raw.get("created_at") or ""), updated_at=str(raw.get("updated_at") or ""),
            status=str(raw.get("status") or "pending"), attempts=max(0, int(raw.get("attempts", 0))),
            max_attempts=max(1, int(raw.get("max_attempts", DEFAULT_MAX_ATTEMPTS))),
            next_attempt_at=_timestamp(raw.get("next_attempt_at")), lease_until=_timestamp(raw.get("lease_until")),
            last_error_code=_safe_component(raw.get("last_error_code") or "", limit=80),
        )
    except (KeyError, TypeError, ValueError):
        return None


def validate_job_descriptor(job: MaintenanceJob) -> str:
    """Return an enumerated error when a queued workspace identity is stale or forged."""
    if job.operation != OPERATION or _safe_identifier(job.project_id) != job.project_id:
        return "invalid_job_identity"
    workspace = Path(job.workspace_root).expanduser()
    try:
        if not workspace.is_absolute() or not workspace.is_dir():
            return "workspace_unavailable"
        for part in (workspace, *workspace.parents):
            if part.is_symlink():
                return "workspace_symlink"
            if part == part.parent:
                break
        context = active_context_from_payload(
            {"cwd": str(workspace), "session_id": job.session_id},
            resolve_git=False,
        )
    except (OSError, ValueError):
        return "workspace_unavailable"
    if context.project_id != job.project_id or context.workspace_instance_id != job.workspace_instance_id:
        return "workspace_identity_mismatch"
    if job.branch and context.branch != job.branch:
        return "stale_branch"
    if job.sha and context.sha and not (context.sha.startswith(job.sha) or job.sha.startswith(context.sha)):
        return "stale_head"
    expected_policy = _safe_component(
        os.environ.get("RALPH_MAINTENANCE_POLICY_VERSION", "maintenance-v1"),
        limit=64,
    )
    if job.policy_version != expected_policy:
        return "stale_policy"
    return ""


def claim_jobs(project_id: str, *, limit: int = 1, lease: int | None = None) -> list[MaintenanceJob]:
    path = queue_path(project_id)
    lock_path = path.with_suffix(path.suffix + ".lock")
    if not _safe_runtime(path) or not _safe_runtime(lock_path):
        return []
    claimed: list[MaintenanceJob] = []
    try:
        with _locked(lock_path) as locked:
            if not locked:
                return []
            state = _load(path)
            now = _epoch()
            original_jobs = state.get("jobs")
            jobs = _trim_jobs(original_jobs, now)
            changed = jobs != original_jobs
            for raw in jobs:
                if len(claimed) >= max(1, min(limit, 32)):
                    break
                if raw.get("status") not in {"pending", "retryable"} or _timestamp(raw.get("next_attempt_at")) > now:
                    continue
                job = _job_from_dict(raw)
                if job is None:
                    continue
                raw["status"] = "leased"
                raw["attempts"] = job.attempts + 1
                raw["lease_until"] = now + float(lease or lease_seconds())
                raw["updated_epoch"] = now
                raw["updated_at"] = now_iso()
                claimed.append(_job_from_dict(raw) or job)
                changed = True
            if changed:
                _atomic_json(path, {"schema_version": SCHEMA_VERSION, "updated_at": now_iso(), "jobs": jobs})
    except (OSError, TypeError, ValueError):
        return []
    return claimed


def complete_job(
    project_id: str,
    job_id: str,
    *,
    success: bool,
    error_code: str = "",
    retryable: bool = True,
) -> bool:
    path = queue_path(project_id)
    lock_path = path.with_suffix(path.suffix + ".lock")
    if not _safe_runtime(path) or not _safe_runtime(lock_path):
        return False
    try:
        with _locked(lock_path) as locked:
            if not locked:
                return False
            state = _load(path)
            jobs = _trim_jobs(state.get("jobs"), _epoch())
            found = False
            now = _epoch()
            for raw in jobs:
                if str(raw.get("job_id")) != job_id:
                    continue
                found = True
                attempts = int(raw.get("attempts", 0))
                if success:
                    raw.update({"status": "completed", "last_error_code": "", "lease_until": 0.0})
                elif not retryable or attempts >= int(raw.get("max_attempts", DEFAULT_MAX_ATTEMPTS)):
                    raw.update({"status": "dead_lettered", "last_error_code": _safe_component(error_code, limit=80), "lease_until": 0.0})
                else:
                    raw.update({"status": "retryable", "last_error_code": _safe_component(error_code, limit=80), "next_attempt_at": now + min(300, 2**attempts), "lease_until": 0.0})
                raw["updated_epoch"] = now
                raw["updated_at"] = now_iso()
                break
            if found:
                _atomic_json(path, {"schema_version": SCHEMA_VERSION, "updated_at": now_iso(), "jobs": jobs})
            return found
    except (OSError, TypeError, ValueError):
        return False


def append_runner_event(*, project_id: str, event: str, job_id: str = "", runtime_ms: float = 0.0, error_code: str = "") -> bool:
    path = event_path(project_id)
    lock_path = path.with_suffix(path.suffix + ".lock")
    if not _safe_runtime(path) or not _safe_runtime(lock_path):
        return False
    payload = {
        "schema_version": SCHEMA_VERSION,
        "created_at": now_iso(),
        "event": _safe_component(event, limit=48),
        "project_id": _safe_component(project_id, limit=80),
        "job_id": _safe_component(job_id, limit=64),
        "runtime_ms": round(max(0.0, float(runtime_ms)), 3),
        "error_code": _safe_component(error_code, limit=80),
    }
    try:
        with _locked(lock_path) as locked:
            if not locked:
                return False
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")
            with contextlib.suppress(OSError):
                path.chmod(0o600)
            _rotate_events(path)
            return True
    except (OSError, TypeError, ValueError):
        return False


def _rotate_events(path: Path) -> None:
    try:
        if path.stat().st_size <= MAX_EVENT_BYTES:
            lines = path.read_text(encoding="utf-8").splitlines()
            if len(lines) <= MAX_EVENT_LINES:
                return
        lines = path.read_text(encoding="utf-8").splitlines()[-MAX_EVENT_LINES:]
        _atomic_json(path.with_suffix(".rotation.json"), {"schema_version": SCHEMA_VERSION, "events": lines})
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        path.with_suffix(".rotation.json").unlink(missing_ok=True)
    except OSError:
        return


def queued_project_ids() -> list[str]:
    root = ralph_home() / "projects"
    try:
        return sorted({path.parent.parent.name for path in root.glob("*/maintenance/queue.json") if path.is_file() and _safe_runtime(path)})
    except OSError:
        return []
