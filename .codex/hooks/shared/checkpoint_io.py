from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX compatibility.
    fcntl = None  # type: ignore[assignment]

from .active_context import ActiveContext, ensure_project_runtime, project_metadata, project_runtime_root
from .paths import _is_allowed_system_alias, append_jsonl, now_iso, ralph_home
from .redaction import redact_text, sensitivity_report

CHECKPOINT_VERSION = 1
CHECKPOINT_DIR = "checkpoints"
MAX_ACTIVE_FILES, MAX_COMMANDS, MAX_LIST_ITEMS = 12, 5, 5
TEXT_LIMITS = {"objective": 240, "current_phase": 160, "last_verified_state": 500, "next_action": 240}
VALID_STATUSES = {"active", "completed", "blocked", "superseded"}
VALID_CLASSIFICATIONS = {"GREEN", "YELLOW", "RED"}
VALID_VALIDATION_STATUSES = {"not_run", "partial", "pass", "fail"}
VALID_SOURCES = {"UserPromptSubmit", "PostToolUse", "Stop", "manual"}
SESSION_START_ACTIVE_TTL_HOURS = 24
SESSION_START_INACTIVE_TTL_HOURS = 12
MAX_CHECKPOINT_BYTES = 256 * 1024
OBSERVATIONAL_CHECKPOINT_FIELDS = frozenset({"updated_at", "content_hash"})
MATERIAL_CHECKPOINT_FIELDS = (
    "status",
    "classification",
    "current_phase",
    "objective",
    "next_action",
    "validation_status",
    "blockers",
    "risk_flags",
)


class CheckpointError(ValueError):
    pass


@dataclass(frozen=True)
class CheckpointWriteResult:
    """Content-free publication metadata for one checkpoint update."""

    changed: bool = False
    bytes_written: int = 0
    files_written: tuple[str, ...] = ()
    archived: bool = False
    replacements: int = 0
    appends: int = 0
    fsync_publications: int = 0
    known: bool = True

    def __bool__(self) -> bool:
        return self.changed


def checkpoint_root(root: Path | None = None, context: ActiveContext | None = None) -> Path:
    if context is not None:
        # Reads (including Stop fingerprinting) must not create project
        # metadata or view directories.  Writers call ensure_checkpoint_runtime
        # explicitly before entering the mutation boundary.
        return project_runtime_root(context, root) / CHECKPOINT_DIR
    return (root or ralph_home()) / CHECKPOINT_DIR


def checkpoint_paths(root: Path | None = None, context: ActiveContext | None = None) -> dict[str, Path]:
    base = checkpoint_root(root, context)
    return {
        "base": base,
        "latest_json": base / "latest.json",
        "latest_md": base / "latest.md",
        "archive": base / "archive",
        "events": base / "events.jsonl",
        "injection_state": base / "injection-state.json",
    }


def ensure_checkpoint_runtime(root: Path | None = None, context: ActiveContext | None = None) -> dict[str, Path]:
    paths = checkpoint_paths(root, context)
    _safe_checkpoint_path(paths["base"], allow_missing=True)
    paths["base"].mkdir(parents=True, exist_ok=True)
    _safe_checkpoint_path(paths["base"])
    paths["base"].chmod(0o700)
    _safe_checkpoint_path(paths["archive"], allow_missing=True)
    paths["archive"].mkdir(parents=True, exist_ok=True)
    _safe_checkpoint_path(paths["archive"])
    paths["archive"].chmod(0o700)
    return paths


def load_latest(root: Path | None = None, context: ActiveContext | None = None) -> dict[str, Any] | None:
    path = checkpoint_paths(root, context)["latest_json"]
    if not path.exists():
        return None
    return read_checkpoint_json(path)


def read_checkpoint_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(_read_checkpoint_bytes(path).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise CheckpointError(f"latest checkpoint is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise CheckpointError("latest checkpoint must be a JSON object")
    return payload


def timestamp_for_filename() -> str:
    return now_iso().replace(":", "").replace("+", "Z")


def compact_error(value: str, limit: int = 240) -> str:
    text = " ".join(value.split())
    return text if len(text) <= limit else text[:limit].rstrip() + "...[truncated]"


def quarantine_invalid_latest(paths: dict[str, Path], error: CheckpointError) -> None:
    source = paths["latest_json"]
    try:
        _safe_checkpoint_path(source)
    except OSError:
        return
    target = paths["base"] / f"latest.invalid.{timestamp_for_filename()}.json"
    try:
        os.replace(source, target)
    except OSError:
        return
    append_jsonl(
        paths["events"],
        {
            "created_at": now_iso(),
            "event": "recovered_invalid_latest",
            "invalid_checkpoint": target.name,
            "error": compact_error(str(error)),
        },
    )


def load_latest_for_update(paths: dict[str, Path], root: Path | None = None, context: ActiveContext | None = None) -> dict[str, Any] | None:
    try:
        return load_latest(root, context)
    except CheckpointError as exc:
        quarantine_invalid_latest(paths, exc)
        return None


@contextmanager
def checkpoint_lock(paths: dict[str, Path]):
    lock_path = paths["base"] / "latest.lock"
    _safe_checkpoint_path(lock_path.parent, allow_missing=True)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    _safe_checkpoint_path(lock_path, allow_missing=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(fd)
        raise OSError("checkpoint lock is not a private regular file")
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def clear_checkpoint(root: Path | None = None, context: ActiveContext | None = None) -> None:
    paths = ensure_checkpoint_runtime(root, context)
    for key in ("latest_json", "latest_md"):
        with suppress(FileNotFoundError):
            paths[key].unlink()
    append_jsonl(paths["events"], {"created_at": now_iso(), "event": "cleared"})


def update_checkpoint(update: dict[str, Any], root: Path | None = None, context: ActiveContext | None = None) -> dict[str, Any]:
    paths = ensure_checkpoint_runtime(root, context)
    progress_ref_only = bool(update.get("progress_ref_only"))
    with checkpoint_lock(paths):
        current = load_latest_for_update(paths, root, context)
        baseline = current or default_checkpoint(context)
        merged = merge_checkpoint(baseline, update, context)
        safety = classify_payload(merged)
        if safety["classification"] == "RED":
            append_jsonl(
                paths["events"],
                {
                    "created_at": now_iso(),
                    "event": "skipped_red",
                    "findings": safety["findings"],
                    "source": merged.get("source", "manual"),
                },
            )
            return {
                "status": "skipped_red",
                "changed": False,
                "bytes_written": 0,
                "files_written": [],
                "replacements": 0,
                "appends": 0,
                "fsync_publications": 0,
                "persistence_bytes_known": True,
                "findings": safety["findings"],
            }

        merged["classification"] = str(safety["classification"])
        rendered = render_checkpoint(merged)
        merged["content_hash"] = content_hash(rendered)
        fingerprint = semantic_fingerprint(merged)
        if current is not None and semantic_fingerprint(current) == fingerprint:
            # Timestamps and the derived content hash are observational.  A
            # repeated semantic update must not publish any checkpoint file or
            # append an event.
            return {
                "status": "unchanged",
                "changed": False,
                "bytes_written": 0,
                "files_written": [],
                "archived": False,
                "replacements": 0,
                "appends": 0,
                "fsync_publications": 0,
                "persistence_bytes_known": True,
                "checkpoint": current,
                "markdown": rendered,
                "semantic_fingerprint": fingerprint,
            }

        write_result = write_checkpoint(
            paths,
            merged,
            rendered,
            archive=(not progress_ref_only) and (current is None or material_checkpoint_transition(current, merged)),
        )
        return {
            "status": "ok",
            "changed": write_result.changed,
            "bytes_written": write_result.bytes_written,
            "files_written": list(write_result.files_written),
            "archived": write_result.archived,
            "replacements": write_result.replacements,
            "appends": write_result.appends,
            "fsync_publications": write_result.fsync_publications,
            "persistence_bytes_known": write_result.known,
            "checkpoint": merged,
            "markdown": rendered,
            "semantic_fingerprint": fingerprint,
        }


def write_checkpoint(
    paths: dict[str, Path],
    checkpoint: dict[str, Any],
    rendered: str,
    *,
    archive: bool = True,
) -> CheckpointWriteResult:
    json_text = json.dumps(checkpoint, indent=2, sort_keys=True) + "\n"
    atomic_write_text(paths["latest_json"], json_text)
    atomic_write_text(paths["latest_md"], rendered)
    files = ["latest.json", "latest.md"]
    bytes_written = len(json_text.encode("utf-8")) + len(rendered.encode("utf-8"))
    archived = False
    if archive:
        timestamp = str(checkpoint["updated_at"]).replace(":", "").replace("+", "Z")
        archive_name = f"{timestamp}-{str(checkpoint.get('content_hash') or '')[:12]}.json"
        atomic_write_text(paths["archive"] / archive_name, json_text)
        files.append(f"archive/{archive_name}")
        bytes_written += len(json_text.encode("utf-8"))
        archived = True
    event = {
        "created_at": checkpoint["updated_at"],
        "event": "updated",
        "content_hash": checkpoint["content_hash"],
        "classification": checkpoint["classification"],
        "source": checkpoint.get("source", "manual"),
        "status": checkpoint.get("status", "active"),
        "project_id": checkpoint.get("project_id", ""),
        "project": checkpoint.get("project", ""),
        "session_id": checkpoint.get("session_id", ""),
    }
    append_jsonl(paths["events"], event)
    event_text = json.dumps(event, ensure_ascii=True, sort_keys=True) + "\n"
    bytes_written += len(event_text.encode("utf-8"))
    files.append("events.jsonl")
    return CheckpointWriteResult(
        changed=True,
        bytes_written=bytes_written,
        files_written=tuple(files),
        archived=archived,
        replacements=len(files) - 1,
        appends=1,
        fsync_publications=2 + int(archived),
    )


def atomic_write_text(path: Path, text: str) -> None:
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_CHECKPOINT_BYTES:
        raise CheckpointError("checkpoint publication exceeds its bounded size")
    path.parent.mkdir(parents=True, exist_ok=True)
    _safe_checkpoint_path(path, allow_missing=True)
    try:
        previous = path.lstat()
    except FileNotFoundError:
        previous = None
    if previous is not None and (stat.S_ISLNK(previous.st_mode) or not stat.S_ISREG(previous.st_mode) or previous.st_nlink != 1):
        raise OSError("checkpoint target is not a private regular file")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        _safe_checkpoint_path(path, allow_missing=True)
        try:
            current = path.lstat()
        except FileNotFoundError:
            current = None
        if previous is None:
            if current is not None:
                raise OSError("checkpoint target appeared during publication")
        elif current is None or (current.st_dev, current.st_ino) != (previous.st_dev, previous.st_ino):
            raise OSError("checkpoint target changed during publication")
        os.replace(tmp_path, path)
        _safe_checkpoint_path(path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        with suppress(FileNotFoundError):
            tmp_path.unlink()


def _safe_checkpoint_path(path: Path, *, allow_missing: bool = False) -> None:
    """Reject aliases and hardlinked files before checkpoint I/O."""

    absolute = path.absolute()
    current = Path(absolute.parts[0])
    for part in absolute.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            if allow_missing:
                continue
            raise OSError(f"checkpoint path does not exist: {current}")
        if stat.S_ISLNK(info.st_mode) and not _is_allowed_system_alias(current):
            raise OSError(f"checkpoint path contains a symlink: {current}")
        if _is_allowed_system_alias(current):
            continue
        if current == absolute:
            if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                raise OSError(f"checkpoint target is hardlinked: {current}")
        elif not stat.S_ISDIR(info.st_mode):
            raise OSError(f"checkpoint path component is not a directory: {current}")


def _read_checkpoint_bytes(path: Path) -> bytes:
    _safe_checkpoint_path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_CHECKPOINT_BYTES:
        raise OSError("checkpoint target is not a bounded regular file")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_size > MAX_CHECKPOINT_BYTES
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise OSError("checkpoint target changed during open")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(64 * 1024, MAX_CHECKPOINT_BYTES - total + 1))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_CHECKPOINT_BYTES:
                raise OSError("checkpoint exceeds its read limit")
        final = os.fstat(fd)
        if (
            final.st_dev != opened.st_dev
            or final.st_ino != opened.st_ino
            or final.st_nlink != 1
            or final.st_size != total
        ):
            raise OSError("checkpoint changed during read")
        return b"".join(chunks)
    finally:
        os.close(fd)


def default_checkpoint(context: ActiveContext | None = None) -> dict[str, Any]:
    cwd = Path.cwd()
    metadata = project_metadata(context) if context is not None else {}
    return {
        "version": CHECKPOINT_VERSION,
        "updated_at": now_iso(),
        "status": "active",
        "classification": "YELLOW",
        "session_id": metadata.get("session_id") or os.environ.get("CODEX_SESSION_ID", ""),
        "cwd": metadata.get("workspace_root") or str(cwd),
        "workspace_root": metadata.get("workspace_root") or str(cwd),
        "git_root": metadata.get("git_root", ""),
        "project": metadata.get("project_slug") or os.environ.get("VAULT_PROJECT") or cwd.name,
        "project_slug": metadata.get("project_slug") or os.environ.get("VAULT_PROJECT") or cwd.name,
        "project_id": metadata.get("project_id", ""),
        "workspace_instance_id": metadata.get("workspace_instance_id", ""),
        "remote_url_hash": metadata.get("remote_url_hash", ""),
        "source_root": metadata.get("ralph_code_root", ""),
        "git_branch": metadata.get("branch") or git_value("rev-parse", "--abbrev-ref", "HEAD"),
        "git_sha": metadata.get("sha") or git_value("rev-parse", "--short", "HEAD"),
        "objective": "",
        "current_phase": "",
        "last_verified_state": "",
        "next_action": "",
        "active_files": [],
        "commands_run": [],
        "blockers": [],
        "risk_flags": [],
        "validation_status": "not_run",
        "source": "manual",
        "content_hash": "",
        "progress_ref": None,
    }


def git_value(*args: str) -> str:
    try:
        result = subprocess.run(["git", *args], text=True, capture_output=True, check=False, timeout=2)
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def merge_checkpoint(current: dict[str, Any], update: dict[str, Any], context: ActiveContext | None = None) -> dict[str, Any]:
    progress_ref = update.get("progress_ref")
    if update.get("progress_ref_only") and isinstance(progress_ref, Mapping):
        # Planned work has one canonical narrative: the implementation store.
        # Keep only a content-free pointer in the rolling checkpoint so the
        # checkpoint cannot become a second objective/phase/validation log.
        merged = default_checkpoint(context)
        identity_fields = (
            "session_id",
            "cwd",
            "workspace_root",
            "git_root",
            "project",
            "project_slug",
            "project_id",
            "workspace_instance_id",
            "remote_url_hash",
            "source_root",
            "git_branch",
            "git_sha",
        )
        for field in identity_fields:
            if current.get(field) not in (None, "", []):
                merged[field] = current[field]
        try:
            plan_id = compact_text(str(progress_ref.get("plan_id", "")), 180)
            generation = int(progress_ref.get("generation", 0))
            semantic_hash = compact_text(str(progress_ref.get("semantic_hash", "")), 80)
        except (TypeError, ValueError):
            raise CheckpointError("progress reference is malformed")
        if not plan_id or generation < 0 or not semantic_hash.startswith("sha256:"):
            raise CheckpointError("progress reference is malformed")
        merged["status"] = "active"
        merged["classification"] = "GREEN"
        merged["source"] = "PostToolUse"
        merged["progress_ref"] = {
            "plan_id": plan_id,
            "generation": generation,
            "semantic_hash": semantic_hash,
        }
        merged["objective"] = ""
        merged["current_phase"] = ""
        merged["last_verified_state"] = ""
        merged["next_action"] = ""
        merged["active_files"] = []
        merged["commands_run"] = []
        merged["blockers"] = []
        merged["risk_flags"] = []
        merged["validation_status"] = "not_run"
        merged["content_hash"] = ""
        validate_checkpoint(merged)
        return merged
    merged = {**default_checkpoint(context), **current}
    merged["version"] = CHECKPOINT_VERSION
    merged["updated_at"] = now_iso()
    if context is not None:
        merged.update(project_metadata(context))
        merged["project"] = context.project_slug
        merged["git_branch"] = context.branch
        merged["git_sha"] = context.sha
        merged["source_root"] = str(context.ralph_code_root)
    else:
        merged["git_branch"] = git_value("rev-parse", "--abbrev-ref", "HEAD")
        merged["git_sha"] = git_value("rev-parse", "--short", "HEAD")

    for field in (
        "status",
        "validation_status",
        "source",
        "classification",
        "session_id",
        "cwd",
        "workspace_root",
        "git_root",
        "project",
        "project_slug",
        "project_id",
        "workspace_instance_id",
        "remote_url_hash",
        "source_root",
    ):
        if update.get(field) is not None:
            merged[field] = str(update[field]).strip()

    for field, limit in TEXT_LIMITS.items():
        if update.get(field) is not None:
            merged[field] = compact_text(str(update[field]), limit)

    for field, limit in (("active_files", MAX_ACTIVE_FILES), ("blockers", MAX_LIST_ITEMS), ("risk_flags", MAX_LIST_ITEMS)):
        if update.get(field) is not None:
            merged[field] = merge_text_list(merged.get(field, []), update[field], limit)

    if update.get("commands_run") is not None:
        merged["commands_run"] = merge_commands(merged.get("commands_run", []), update["commands_run"])

    validate_checkpoint(merged)
    return merged


def validate_checkpoint(checkpoint: dict[str, Any]) -> None:
    if checkpoint.get("version") != CHECKPOINT_VERSION:
        raise CheckpointError(f"checkpoint version must be {CHECKPOINT_VERSION}")
    if str(checkpoint.get("status", "")) not in VALID_STATUSES:
        raise CheckpointError(f"status must be one of {sorted(VALID_STATUSES)}")
    if str(checkpoint.get("classification", "")).upper() not in VALID_CLASSIFICATIONS:
        raise CheckpointError(f"classification must be one of {sorted(VALID_CLASSIFICATIONS)}")
    if str(checkpoint.get("validation_status", "")) not in VALID_VALIDATION_STATUSES:
        raise CheckpointError(f"validation_status must be one of {sorted(VALID_VALIDATION_STATUSES)}")
    if str(checkpoint.get("source", "")) not in VALID_SOURCES:
        raise CheckpointError(f"source must be one of {sorted(VALID_SOURCES)}")
    for field in ("active_files", "commands_run", "blockers", "risk_flags"):
        if not isinstance(checkpoint.get(field), list):
            raise CheckpointError(f"{field} must be a list")


def _semantic_payload(checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    """Return the checkpoint fields that describe durable task state."""

    return {
        str(key): value
        for key, value in checkpoint.items()
        if str(key) not in OBSERVATIONAL_CHECKPOINT_FIELDS
    }


def semantic_fingerprint(checkpoint: Mapping[str, Any]) -> str:
    """Hash checkpoint meaning without observational publication fields."""

    encoded = json.dumps(_semantic_payload(checkpoint), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def material_checkpoint_transition(current: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    """Identify boundaries worth retaining in the rolling archive.

    Command/file observations still update ``latest.json`` and its event, but
    they do not grow the archive unless task status, phase, validation, safety,
    or the explicit objective/action state changes.
    """

    return any(current.get(field) != candidate.get(field) for field in MATERIAL_CHECKPOINT_FIELDS)


def classify_payload(checkpoint: dict[str, Any]) -> dict[str, Any]:
    requested = str(checkpoint.get("classification") or "YELLOW").upper()
    if requested == "RED":
        return {"classification": "RED", "findings": [{"kind": "classification", "label": "requested_red", "severity": "RED"}]}
    text = json.dumps(red_check_material(checkpoint), ensure_ascii=True, sort_keys=True)
    report = sensitivity_report(text)
    if not isinstance(report, dict):
        return {"classification": "RED", "findings": []}
    if report.get("classification") == "RED":
        return report
    return {**report, "classification": requested if requested in {"GREEN", "YELLOW"} else "YELLOW"}


def red_check_material(checkpoint: dict[str, Any]) -> dict[str, Any]:
    return {
        "objective": checkpoint.get("objective", ""),
        "current_phase": checkpoint.get("current_phase", ""),
        "last_verified_state": checkpoint.get("last_verified_state", ""),
        "next_action": checkpoint.get("next_action", ""),
        "active_files": checkpoint.get("active_files", []),
        "commands_run": checkpoint.get("commands_run", []),
        "blockers": checkpoint.get("blockers", []),
        "risk_flags": checkpoint.get("risk_flags", []),
    }


def render_checkpoint(checkpoint: dict[str, Any], max_words: int = 500) -> str:
    lines = ["Continuity checkpoint:"]
    append_line(lines, "Objective", checkpoint.get("objective"))
    append_line(lines, "Current phase", checkpoint.get("current_phase"))
    append_line(lines, "Last verified state", checkpoint.get("last_verified_state"))
    append_line(lines, "Next action", checkpoint.get("next_action"))
    if checkpoint.get("active_files"):
        lines.append(f"Relevant paths: {', '.join(str(item) for item in checkpoint['active_files'][:MAX_ACTIVE_FILES])}")
    append_line(lines, "Validation", checkpoint.get("validation_status"))
    if checkpoint.get("blockers"):
        lines.append(f"Blockers: {'; '.join(str(item) for item in checkpoint['blockers'][:MAX_LIST_ITEMS])}")
    if checkpoint.get("risk_flags"):
        lines.append(f"Risks: {'; '.join(str(item) for item in checkpoint['risk_flags'][:MAX_LIST_ITEMS])}")
    rendered = redact_text("\n".join(lines).strip() + "\n")
    return compact_words(rendered, max_words)


def render_latest_for_wakeup(root: Path | None = None, max_words: int = 500, context: ActiveContext | None = None) -> str:
    try:
        checkpoint = load_latest(root, context)
    except CheckpointError:
        return ""
    if not checkpoint or not checkpoint_is_injectable(checkpoint, context):
        return ""
    return render_checkpoint(checkpoint, max_words=max_words).strip()


def checkpoint_is_injectable(checkpoint: dict[str, Any], context: ActiveContext | None = None) -> bool:
    if context is not None:
        checkpoint_project = str(checkpoint.get("project_id") or "").strip()
        if checkpoint_project != context.project_id:
            return False
        checkpoint_session = str(checkpoint.get("session_id") or "").strip()
        if checkpoint_session != context.session_id:
            return False
        checkpoint_workspace = str(checkpoint.get("workspace_instance_id") or "").strip()
        if checkpoint_workspace != context.workspace_instance_id:
            return False
        checkpoint_branch = str(checkpoint.get("git_branch") or "").strip()
        if checkpoint_branch and context.branch and checkpoint_branch != context.branch:
            return False
    if str(checkpoint.get("classification", "")).upper() == "RED":
        return False
    if not str(checkpoint.get("objective", "")).strip() or not str(checkpoint.get("next_action", "")).strip():
        return False
    if is_stale(checkpoint):
        return False
    return classify_payload(checkpoint)["classification"] != "RED"


def is_stale(checkpoint: dict[str, Any]) -> bool:
    updated_at = parse_time(str(checkpoint.get("updated_at", "")))
    if updated_at is None:
        return True
    ttl_hours = SESSION_START_ACTIVE_TTL_HOURS if checkpoint.get("status") == "active" else SESSION_START_INACTIVE_TTL_HOURS
    return datetime.now(UTC) - updated_at > timedelta(hours=ttl_hours)


def parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def append_line(lines: list[str], label: str, value: object) -> None:
    text = str(value or "").strip()
    if text:
        lines.append(f"{label}: {text}")


def compact_text(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "...[truncated]"


def merge_text_list(current: object, update: object, limit: int) -> list[str]:
    values = list(current) if isinstance(current, list) else []
    incoming = update if isinstance(update, list) else [update]
    for item in incoming:
        text = compact_text(str(item), 220)
        if text and text not in values:
            values.append(text)
    return values[-limit:]


def merge_commands(current: object, update: object) -> list[dict[str, str]]:
    values = [item for item in current if isinstance(item, dict)] if isinstance(current, list) else []
    incoming = update if isinstance(update, list) else [update]
    for item in incoming:
        if not isinstance(item, dict):
            continue
        normalized = {
            "command": compact_text(str(item.get("command", "")), 180),
            "result": compact_text(str(item.get("result", "unknown")), 20),
            "summary": compact_text(str(item.get("summary", "")), 220),
        }
        if normalized not in values:
            values.append(normalized)
    return values[-MAX_COMMANDS:]


def compact_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip() + " ...[truncated]"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def doctor(root: Path | None = None) -> tuple[bool, list[str]]:
    messages: list[str] = []
    paths = ensure_checkpoint_runtime(root)
    checkpoint = load_latest(root)
    if checkpoint is None:
        messages.append("latest checkpoint missing")
        return False, messages
    try:
        validate_checkpoint(checkpoint)
    except CheckpointError as exc:
        messages.append(str(exc))
    rendered = render_checkpoint(checkpoint)
    if len(rendered.split()) > 500:
        messages.append("render exceeds 500 words")
    if classify_payload(checkpoint)["classification"] == "RED":
        messages.append("checkpoint classified RED")
    if not paths["archive"].is_dir():
        messages.append("archive directory missing")
    return not messages, messages or ["ok"]
