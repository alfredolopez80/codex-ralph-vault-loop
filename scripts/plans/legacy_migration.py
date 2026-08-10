"""Reader-first, reversible migration of legacy implementation notes.

The normal progress path never imports this module.  ``progress.py`` exposes
it only through the explicit ``migrate-legacy`` and ``rebuild-legacy``
maintenance commands.  The migration reads every legacy source into a bounded
in-memory inventory, refuses ambiguous evidence by default, and writes only
the canonical ``.local-notes/ralph/implementation`` store.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from implementation_notes_consolidator import unsafe_notes_html_match
from implementation_notes_lib import (
    ALLOWED_CATEGORIES,
    CATEGORY_ORDER,
    ImplementationNotesError,
    NotesHTMLParser,
    ensure_not_red,
)
from shared.implementation_store import (
    ImplementationStore,
    StoreError,
    StorePathError,
    StoreResult,
)
from shared.implementation_store.io import StoreIOError, locked_file, publish_bytes
from shared.implementation_store.paths import StorePaths, _reject_symlink_components, ensure_store_layout, validate_plan_id
from shared.implementation_store.schema import (
    canonical_json,
    digest,
    encoded_size,
    event_record_hash,
    new_state,
    validate_state,
)


INDEX_SCHEMA_VERSION = 2
LEGACY_NOTE_SUFFIX = "-implementation-notes.html"
INDEX_JSON_NAME = "implementation-index.json"
INDEX_MD_NAME = "implementation-index.md"
CONSOLIDATED_HTML_NAME = "implementation-notes-consolidated.html"
CONSOLIDATED_MD_NAME = "implementation-notes-consolidated.md"
MAX_FILES = 2_000
MAX_SCANNED_ENTRIES = MAX_FILES * 4
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TEXT = 400
MAX_REASON = 400
MAX_REFERENCES = 8
MAX_EVENTS_PER_PLAN = 512
MAX_DERIVED_VIEW_BYTES = 256 * 1024
VALID_STATUSES = frozenset({"planned", "active", "completed", "blocked", "superseded", "reopened"})
VALID_RESULTS = frozenset({"not_run", "pending", "partial", "pass", "fail", "blocked"})
SENSITIVE_NAME_RE = re.compile(
    r"(?i)(^\.env(?:\.|$)|secret|token|credential|wallet|keystore|cookies?|id_rsa|id_ed25519|\.pem$|\.key$)"
)
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,95}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{7,64}$")


class MigrationError(RuntimeError):
    """A bounded, user-visible migration failure."""

    def __init__(self, code: str, message: str, *, report: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.report = dict(report or {})


@dataclass(frozen=True)
class Artifact:
    path: Path
    root: Path
    relative: str
    kind: str
    digest: str
    bytes: int
    mtime_ns: int
    inode: tuple[int, int] | None
    alias_reason: str = ""

    def snapshot(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "relative": self.relative,
            "kind": self.kind,
            "digest": self.digest,
            "bytes": self.bytes,
            "mtime_ns": self.mtime_ns,
            "alias_reason": self.alias_reason,
        }


@dataclass(frozen=True)
class PlanCopy:
    artifact: Artifact
    plan_id: str
    approved: bool
    metadata: dict[str, str]
    digest: str
    error: str = ""
    content_signature: str = ""


@dataclass(frozen=True)
class ParsedNote:
    artifact: Artifact
    plan_id: str
    text_digest: str
    initial: Any | None
    entries: tuple[Any, ...]
    document_fields: dict[str, str]


@dataclass(frozen=True)
class IndexCopy:
    artifact: Artifact
    data: dict[str, Any] | None
    schema: str
    error: str = ""


@dataclass(frozen=True)
class EventSpec:
    plan_id: str
    kind: str
    operation_id: str
    timestamp: str
    summary: str
    reason: str
    next_action: str
    references: tuple[str, ...]
    status: str
    phase: str
    category: str
    evidence_codes: tuple[str, ...]
    provenance: dict[str, Any]
    source: str
    source_digest: str
    source_event_id: str = ""

    def payload_signature(self) -> str:
        return digest(
            {
                "plan_id": self.plan_id,
                "kind": self.kind,
                "operation_id": self.operation_id,
                "timestamp": self.timestamp,
                "summary": self.summary,
                "reason": self.reason,
                "next_action": self.next_action,
                "references": list(self.references),
                "status": self.status,
                "phase": self.phase,
                "category": self.category,
                "evidence_codes": list(self.evidence_codes),
                "provenance": self.provenance,
            }
        )


@dataclass
class PlanMigration:
    plan_id: str
    plan_rel: str
    plan_source: Artifact | None = None
    plan_copies: list[PlanCopy] = field(default_factory=list)
    note_copies: list[Artifact] = field(default_factory=list)
    selected_note: Artifact | None = None
    parsed_note: ParsedNote | None = None
    approved: bool = False
    events: list[EventSpec] = field(default_factory=list)
    conflicts: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class MigrationContext:
    paths: StorePaths
    active_root: Path
    recovery_mode: bool
    roots: tuple[Path, ...]
    artifacts: list[Artifact]
    plans: dict[str, PlanMigration]
    indexes: list[IndexCopy]
    index_events: list[dict[str, Any]]
    loose_commits: list[dict[str, Any]]
    conflicts: list[dict[str, str]]
    aliases: list[dict[str, str]]
    corrupt_schemas: list[dict[str, str]]
    future_schemas: list[dict[str, str]]
    missing_plans: list[str]
    orphan_views: list[str]
    warnings: list[str]
    loose_sources: list[dict[str, Any]]

    @property
    def blocked(self) -> bool:
        return bool(
            self.conflicts
            or self.aliases
            or self.corrupt_schemas
            or self.future_schemas
            or self.missing_plans
            or self.orphan_views
        )


def _digest_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _snapshot_rollback_target(target: Path) -> tuple[bytes, int] | None:
    """Capture one bounded legacy target before a multi-file publication."""
    try:
        _reject_symlink_components(target.parent, allow_missing=True)
        info = target.lstat()
    except FileNotFoundError:
        return None
    except (OSError, StorePathError) as exc:
        raise MigrationError("rollback_target_alias", "legacy rollback target cannot be inspected") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise MigrationError("rollback_target_alias", "legacy rollback target is an unsafe alias")
    try:
        raw, final = _read_bounded_file(target, max_bytes=MAX_DERIVED_VIEW_BYTES)
    except (OSError, StorePathError, MigrationError) as exc:
        raise MigrationError("rollback_target_alias", "legacy rollback target cannot be snapshotted") from exc
    return raw, stat.S_IMODE(final.st_mode)


def _restore_rollback_target(target: Path, snapshot: tuple[bytes, int] | None) -> None:
    """Restore one target after a failed batch publication."""
    _reject_symlink_components(target.parent, allow_missing=True)
    if snapshot is None:
        try:
            info = target.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise OSError("rollback target changed to an unsafe alias")
        target.unlink()
    else:
        publish_bytes(target, snapshot[0], hard_limit=MAX_DERIVED_VIEW_BYTES)
        os.chmod(target, snapshot[1])
    directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _read_bounded_file(
    path: Path,
    *,
    max_bytes: int,
    expected_inode: tuple[int, int] | None = None,
    expected_digest: str = "",
) -> tuple[bytes, os.stat_result]:
    """Read a legacy source through one stable, no-follow descriptor."""

    try:
        before = path.lstat()
    except OSError as exc:
        raise OSError("legacy source cannot be inspected") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise OSError("legacy source is an alias or non-regular file")
    if expected_inode is not None and (before.st_dev, before.st_ino) != expected_inode:
        raise MigrationError("legacy_changed", "legacy source changed identity after inventory")
    if before.st_size > max_bytes:
        raise OSError("legacy source exceeds its read limit")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise OSError("legacy source cannot be opened safely") from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or opened.st_size > max_bytes:
            raise OSError("legacy source changed to an unsafe file")
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise MigrationError("legacy_changed", "legacy source changed identity during read")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(64 * 1024, max_bytes - total + 1))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise OSError("legacy source exceeds its read limit")
        final = os.fstat(fd)
        if (
            final.st_dev != opened.st_dev
            or final.st_ino != opened.st_ino
            or final.st_nlink != 1
            or final.st_size != total
        ):
            raise MigrationError("legacy_changed", "legacy source changed during read")
        data = b"".join(chunks)
    finally:
        os.close(fd)
    if expected_digest and _digest_bytes(data) != expected_digest:
        raise MigrationError("legacy_changed", "legacy source changed after inventory")
    return data, final


def _bounded(value: object, limit: int = MAX_TEXT) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _safe_id(value: str, fallback: str) -> str:
    value = _bounded(value, 96)
    return value if IDENTIFIER_RE.fullmatch(value) else fallback


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, text=True, capture_output=True, check=False, timeout=3
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _git_provenance(root: Path, *, branch: str = "", commit: str = "", session: str = "", workspace: str = "") -> dict[str, Any]:
    branch = _bounded(branch or _git(root, "branch", "--show-current") or _git(root, "rev-parse", "--abbrev-ref", "HEAD"), 240)
    commit = _bounded(commit or _git(root, "rev-parse", "HEAD"), 80)
    if commit and not COMMIT_RE.fullmatch(commit):
        commit = ""
    if not workspace:
        workspace = "ws-" + hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:16]
    return {
        "git": {"branch": branch, "commit": commit, "workspace_instance_id": _safe_id(workspace, "legacy-worktree")},
        "writer_session_id": _safe_id(session, "legacy") if session else "legacy",
        "model_family": "unknown",
        "model_source": "unknown",
        "model_verified": False,
        "origin": "implementation-progress",
        "intent": "progress-maintenance",
    }


def _source_root_for_path(path: Path, roots: Iterable[Path]) -> Path:
    candidates = [root for root in roots if path == root or path.is_relative_to(root)]
    if not candidates:
        return path.parent
    return max(candidates, key=lambda item: len(item.parts))


def _worktree_roots(primary: Path, active: Path) -> tuple[Path, ...]:
    candidates: list[Path] = [primary.resolve(), active.resolve()]
    raw = _git(active, "worktree", "list", "--porcelain")
    current: Path | None = None
    for line in raw.splitlines():
        if line.startswith("worktree "):
            current = Path(line.split(" ", 1)[1]).expanduser()
        elif not line and current is not None:
            if current.exists():
                candidates.append(current.resolve())
            current = None
    if current is not None and current.exists():
        candidates.append(current.resolve())
    result: list[Path] = []
    for candidate in candidates:
        if candidate not in result:
            result.append(candidate)
    return tuple(result)


def _artifact_kind(path: Path) -> str:
    name = path.name
    if name == INDEX_JSON_NAME:
        return "index-json"
    if name.startswith(INDEX_JSON_NAME + ".corrupt-"):
        return "index-json-corrupt-copy"
    if name == INDEX_MD_NAME:
        return "index-markdown"
    if name in {CONSOLIDATED_HTML_NAME, CONSOLIDATED_MD_NAME}:
        return "consolidated-html" if name.endswith(".html") else "consolidated-markdown"
    if name.endswith(LEGACY_NOTE_SUFFIX):
        return "notes-html"
    if path.suffix.lower() in {".md", ".markdown"}:
        return "plan-markdown"
    return ""


def _scan_artifacts(roots: tuple[Path, ...], primary: Path) -> tuple[list[Artifact], list[dict[str, str]]]:
    artifacts: list[Artifact] = []
    aliases: list[dict[str, str]] = []
    inode_seen: dict[tuple[int, int], Path] = {}
    for root in roots:
        plans_root = root / ".ralph" / "plans"
        if not plans_root.exists():
            continue
        if plans_root.is_symlink():
            aliases.append({"path": str(plans_root), "reason": "plans root is a symlink"})
            continue
        pending = [plans_root]
        scanned = 0
        while pending:
            current = pending.pop()
            try:
                entries = sorted(os.scandir(current), key=lambda entry: entry.name)
            except OSError as exc:
                aliases.append({"path": str(current), "reason": f"cannot scan source: {exc.__class__.__name__}"})
                continue
            for entry in entries:
                scanned += 1
                if scanned > MAX_SCANNED_ENTRIES:
                    raise MigrationError("legacy_limit", "legacy directory traversal exceeds the migration limit")
                path = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                    continue
                kind = _artifact_kind(path)
                if not kind:
                    if path.is_symlink():
                        aliases.append({"path": str(path), "reason": "symlink alias"})
                    continue
                try:
                    info = path.lstat()
                except OSError as exc:
                    aliases.append({"path": str(path), "reason": f"cannot inspect source: {exc.__class__.__name__}"})
                    continue
                rel = path.relative_to(plans_root).as_posix()
                alias_reason = ""
                inode = (info.st_dev, info.st_ino)
                if stat.S_ISLNK(info.st_mode):
                    alias_reason = "symlink alias"
                elif not stat.S_ISREG(info.st_mode):
                    alias_reason = "non-regular source"
                elif info.st_nlink != 1:
                    alias_reason = "hardlink alias"
                elif inode in inode_seen and inode_seen[inode] != path:
                    alias_reason = f"same inode as {inode_seen[inode]}"
                else:
                    inode_seen[inode] = path
                digest_value = ""
                size = int(info.st_size)
                if not alias_reason:
                    if size > MAX_FILE_BYTES:
                        alias_reason = "source exceeds migration size limit"
                    else:
                        try:
                            raw, _stat = _read_bounded_file(path, max_bytes=MAX_FILE_BYTES)
                            digest_value = _digest_bytes(raw)
                        except (OSError, ValueError) as exc:
                            alias_reason = f"cannot read source: {exc.__class__.__name__}"
                artifact = Artifact(
                    path=path,
                    root=root,
                    relative=rel,
                    kind=kind,
                    digest=digest_value,
                    bytes=size,
                    mtime_ns=int(info.st_mtime_ns),
                    inode=inode,
                    alias_reason=alias_reason,
                )
                artifacts.append(artifact)
                if alias_reason:
                    aliases.append({"path": str(path), "reason": alias_reason})
    if len(artifacts) > MAX_FILES:
        raise MigrationError("legacy_limit", "legacy artifact count exceeds the migration limit")
    return artifacts, aliases


def _plan_id_from_relative(relative: str) -> str:
    path = Path(relative)
    if path.suffix.lower() in {".md", ".markdown"}:
        path = path.with_suffix("")
    plan_id = path.as_posix()
    validate_plan_id(plan_id)
    return plan_id


def _plan_metadata(text: str) -> tuple[dict[str, str], bool]:
    values: dict[str, str] = {}
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence or ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
        if normalized in {"implementation_notes", "implementation_notes_required", "implementation_notes_status", "plan_approval_status"} and normalized not in values:
            values[normalized] = value.strip()
    approved = values.get("plan_approval_status", "").strip().lower() == "approved"
    return values, approved


def _plan_content_signature(text: str) -> str:
    """Ignore only the generated notes pointer when comparing plan copies."""

    kept: list[str] = []
    for line in text.splitlines():
        if ":" in line:
            key, _value = line.split(":", 1)
            normalized = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
            if normalized == "implementation_notes":
                continue
        kept.append(line.rstrip())
    return digest("\n".join(kept).strip())


def _read_text(artifact: Artifact) -> str:
    if artifact.alias_reason:
        raise MigrationError("source_alias", "legacy source is an alias or cannot be read")
    try:
        raw, _stat = _read_bounded_file(
            artifact.path,
            max_bytes=MAX_FILE_BYTES,
            expected_inode=artifact.inode,
            expected_digest=artifact.digest,
        )
        text = raw.decode("utf-8")
        ensure_not_red("legacy migration source", text)
    except MigrationError:
        raise
    except (OSError, UnicodeError) as exc:
        raise MigrationError("legacy_invalid", "legacy source cannot be decoded") from exc
    except ImplementationNotesError as exc:
        raise MigrationError("legacy_invalid", "legacy source contains RED-sensitive material") from exc
    return text


def _parse_notes_once(artifact: Artifact, plan_id: str) -> ParsedNote:
    text = _read_text(artifact)
    unsafe = unsafe_notes_html_match(text)
    if unsafe:
        raise MigrationError("legacy_invalid", "legacy implementation notes contain unsafe HTML")
    parser = NotesHTMLParser()
    parser.feed(text)
    parser.close()
    if not parser.has_main or not parser.has_csp:
        raise MigrationError("legacy_invalid", "legacy implementation notes are missing required markers")
    for category in CATEGORY_ORDER:
        if parser.section_counts.get(category) != 1:
            raise MigrationError("legacy_invalid", "legacy implementation notes have an invalid section layout")
        if parser.anchor_sections.get(category) != category:
            raise MigrationError("legacy_invalid", "legacy implementation notes have an invalid anchor layout")
    initial: Any | None = None
    entries: list[Any] = []
    for entry in parser.entries:
        if entry.category == "initial":
            if initial is not None:
                raise MigrationError("legacy_invalid", "legacy implementation notes contain duplicate initial templates")
            initial = entry
            continue
        if entry.category not in ALLOWED_CATEGORIES or entry.section != entry.category:
            raise MigrationError("legacy_invalid", "legacy implementation notes contain an invalid entry category")
        required = ("Timestamp", "Category", "Decision", "Reason", "Impact", "Related files", "Status")
        if any(not entry.fields.get(field) for field in required) or entry.fields.get("Category") != entry.category:
            raise MigrationError("legacy_invalid", "legacy implementation notes contain an incomplete entry")
        entries.append(entry)
    return ParsedNote(
        artifact=artifact,
        plan_id=plan_id,
        text_digest=artifact.digest,
        initial=initial,
        entries=tuple(entries),
        document_fields=dict(parser.document_fields),
    )


def _normalize_status(raw: str, *, default: str = "active") -> str:
    normalized = _bounded(raw, 40).strip().lower().replace(" ", "_").replace("-", "_")
    mapping = {
        "implemented": "completed",
        "complete": "completed",
        "done": "completed",
        "in_progress": "active",
        "in-progress": "active",
        "open": "active",
        "closed": "completed",
        "resolved": "completed",
        "blocked_open": "blocked",
    }
    normalized = mapping.get(normalized, normalized)
    return normalized if normalized in VALID_STATUSES else default


def _normalize_result(raw: str) -> str:
    normalized = _normalize_status(raw, default="pending")
    return normalized if normalized in VALID_RESULTS else "pending"


def _timestamp(raw: str, fallback: str = "") -> str:
    value = _bounded(raw, 64)
    if value:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MigrationError("legacy_invalid", "legacy material entry has an invalid timestamp") from exc
        return value
    return fallback


def _references(raw: str) -> tuple[str, ...]:
    values: list[str] = []
    for part in re.split(r"[,;]\s*", raw):
        value = _bounded(part, 320)
        if not value or value.lower() == "n/a":
            continue
        # The canonical event schema deliberately keeps references repository
        # relative.  URLs and prose remain represented by a bounded evidence
        # code rather than becoming an unsafe path.
        if value.startswith("/") or "//" in value or any(piece in {"", ".", ".."} for piece in value.split("/")):
            continue
        values.append(value)
    return tuple(dict.fromkeys(values[:MAX_REFERENCES]))


def _operation_id(raw: str, *, source: Artifact, plan_id: str, ordinal: int, category: str, timestamp: str, summary: str) -> str:
    supplied = _bounded(raw, 96)
    if supplied:
        if not IDENTIFIER_RE.fullmatch(supplied):
            raise MigrationError("legacy_invalid", "legacy operation ID is outside the canonical bound")
        return supplied
    material = "\n".join([plan_id, source.relative, category, timestamp, summary, str(ordinal)])
    return "mig-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:40]


def _entry_hash(entry: Any) -> str:
    material = "\n".join(
        [
            str(entry.category),
            str(entry.fields.get("Timestamp", "")),
            str(entry.fields.get("Decision", "")),
            str(entry.fields.get("Status", "")),
            str(entry.fields.get("Operation ID", "")),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _event_kind(category: str, status: str) -> str:
    normalized = status.lower().replace("-", "_")
    if category == "validation":
        return "validation_changed"
    if category == "open-question":
        return "question_resolved" if normalized in {"resolved", "closed", "complete"} else "question_opened"
    if normalized in {"blocked", "blocker", "blocked_open"}:
        return "blocker_opened"
    if normalized in {"resolved", "closed", "complete", "completed", "implemented", "done"} and category == "summary":
        return "completed"
    if category == "deviation":
        return "deviation"
    if category in {"summary", "tradeoff"}:
        return "migration_imported" if category == "summary" else "decision"
    return "decision"


def _status_evidence_code(raw: str, normalized: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", _bounded(raw, 40).strip().lower()).strip("-")
    return "legacy-status-" + (value or normalized)


def _provenance_from_note(note: ParsedNote, root: Path) -> dict[str, Any]:
    fields = note.document_fields
    return _git_provenance(
        root,
        branch=fields.get("Git branch", ""),
        commit=fields.get("Git SHA", ""),
        session=fields.get("Session id", ""),
        workspace=fields.get("Workspace instance id", ""),
    )


def _spec_from_entry(entry: Any, *, note: ParsedNote, ordinal: int, provenance: dict[str, Any]) -> EventSpec:
    timestamp = _timestamp(entry.fields.get("Timestamp", ""))
    summary = _bounded(entry.fields.get("Decision", ""))
    category = _bounded(entry.category, 80)
    status_raw = entry.fields.get("Status", "")
    status = _normalize_status(status_raw)
    kind = _event_kind(category, status_raw)
    operation_id = _operation_id(
        entry.fields.get("Operation ID", ""),
        source=note.artifact,
        plan_id=note.plan_id,
        ordinal=ordinal,
        category=category,
        timestamp=timestamp,
        summary=summary,
    )
    codes = [f"legacy-category-{category.replace('_', '-')}", "legacy-html", _status_evidence_code(status_raw, status)]
    if not _references(entry.fields.get("Related files", "")) and entry.fields.get("Related files", "").strip().lower() not in {"", "n/a"}:
        codes.append("legacy-reference-bounded")
    return EventSpec(
        plan_id=note.plan_id,
        kind=kind,
        operation_id=operation_id,
        timestamp=timestamp,
        summary=summary,
        reason=_bounded(entry.fields.get("Reason", ""), MAX_REASON),
        next_action=_bounded(entry.fields.get("Impact", ""), MAX_REASON),
        references=_references(entry.fields.get("Related files", "")),
        status=status,
        phase=_bounded(entry.fields.get("Phase", ""), 160),
        category=category,
        evidence_codes=tuple(codes),
        provenance=provenance,
        source="legacy-html",
        source_digest=note.text_digest,
    )


def _spec_from_initial(note: ParsedNote, *, plan_rel: str, plan_root: Path, approved: bool) -> EventSpec:
    entry = note.initial
    fields = entry.fields if entry is not None else {}
    timestamp = _timestamp(fields.get("Timestamp", ""), _timestamp(note.document_fields.get("Implementation start", ""), ""))
    if not timestamp:
        timestamp = datetime.fromtimestamp(note.artifact.mtime_ns / 1_000_000_000, tz=UTC).replace(microsecond=0).isoformat()
    summary = _bounded(fields.get("Decision", "Implementation started")) or "Implementation started"
    status = _normalize_status(fields.get("Status", "active"), default="active")
    provenance = _provenance_from_note(note, note.artifact.root)
    return EventSpec(
        plan_id=note.plan_id,
        kind="started",
        operation_id=_operation_id(
            fields.get("Operation ID", ""),
            source=note.artifact,
            plan_id=note.plan_id,
            ordinal=0,
            category="initial",
            timestamp=timestamp,
            summary=summary,
        ),
        timestamp=timestamp,
        summary=summary,
        reason=_bounded(fields.get("Reason", ""), MAX_REASON) or "Legacy implementation notes template",
        next_action=_bounded(fields.get("Impact", ""), MAX_REASON),
        references=_references(fields.get("Related files", "")),
        status=status,
        phase=_bounded(fields.get("Phase", ""), 160),
        category="initial",
        evidence_codes=("legacy-template", "legacy-html", "legacy-approved" if approved else "legacy-unapproved"),
        provenance=provenance,
        source="legacy-html",
        source_digest=note.text_digest,
    )


def _spec_from_index(event: Mapping[str, Any], *, plan_id: str, source: IndexCopy) -> EventSpec:
    event_name = _bounded(str(event.get("event", "")), 80)
    status_raw = str(event.get("status", ""))
    status = _normalize_status(status_raw)
    if event_name == "implemented":
        kind = "completed"
    elif event_name == "guard_validated":
        kind = "validation_changed"
    elif event_name == "notes_created":
        kind = "started"
    elif event_name == "note_appended":
        kind = "decision"
    else:
        kind = "migration_imported"
    timestamp = _timestamp(
        str(event.get("timestamp") or event.get("created_at") or ""),
        datetime.fromtimestamp(source.artifact.mtime_ns / 1_000_000_000, tz=UTC).replace(microsecond=0).isoformat(),
    )
    event_id = _bounded(str(event.get("event_id", "")), 96)
    operation = _bounded(str(event.get("operation_id", "")), 96)
    if not operation:
        operation = "idx-" + hashlib.sha256((source.artifact.relative + "\n" + event_id + "\n" + timestamp).encode()).hexdigest()[:40]
    provenance = _git_provenance(
        source.artifact.root,
        branch=str(event.get("branch", "")),
        commit=str(event.get("commit", "")),
        session=str(event.get("session_id", "")),
        workspace=str(event.get("workspace_instance_id", "")),
    )
    summary = _bounded(str(event.get("summary") or event.get("reason") or event_name))
    return EventSpec(
        plan_id=plan_id,
        kind=kind,
        operation_id=operation,
        timestamp=timestamp,
        summary=summary,
        reason=_bounded(str(event.get("reason", "")), MAX_REASON),
        next_action=_bounded(str(event.get("notes_detail") or event.get("notes") or ""), MAX_REASON),
        references=(),
        status=status,
        phase="",
        category="index",
        evidence_codes=("legacy-index-event", f"legacy-index-{event_name or 'unknown'}"),
        provenance=provenance,
        source="legacy-index",
        source_digest=source.artifact.digest,
        source_event_id=event_id,
    )


def _plan_record(plans: dict[str, PlanMigration], plan_id: str) -> PlanMigration:
    return plans.setdefault(plan_id, PlanMigration(plan_id=plan_id, plan_rel=f".ralph/plans/{plan_id}.md"))


def _index_event_checksum_ok(event: Mapping[str, Any]) -> bool:
    checksum_fields = [field for field in ("checksum", "event_hash") if event.get(field)]
    for field in checksum_fields:
        supplied = str(event.get(field, ""))
        material = {key: value for key, value in event.items() if key not in {field, "checksum", "event_hash", "event_id", "created_at", "timestamp"}}
        expected_hex = hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()
        if supplied not in {expected_hex, "sha256:" + expected_hex}:
            return False
    event_id = event.get("event_id")
    if not event_id:
        return True
    material = {key: value for key, value in event.items() if key not in {"event_id", "created_at", "timestamp"}}
    expected = hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()
    return str(event_id) == expected


def _parse_index(artifact: Artifact) -> IndexCopy:
    if artifact.alias_reason:
        return IndexCopy(artifact, None, "alias", artifact.alias_reason)
    try:
        raw_bytes, _stat = _read_bounded_file(
            artifact.path,
            max_bytes=MAX_FILE_BYTES,
            expected_inode=artifact.inode,
            expected_digest=artifact.digest,
        )
        raw = raw_bytes.decode("utf-8")
        ensure_not_red("legacy implementation index", raw)
        data = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return IndexCopy(artifact, None, "corrupt", "implementation index is not valid JSON")
    except ImplementationNotesError:
        return IndexCopy(artifact, None, "corrupt", "implementation index contains RED-sensitive material")
    if not isinstance(data, dict):
        return IndexCopy(artifact, None, "corrupt", "implementation index must be an object")
    version = data.get("version")
    if isinstance(version, int) and version > INDEX_SCHEMA_VERSION:
        return IndexCopy(artifact, None, "future", f"implementation index schema {version} is newer than {INDEX_SCHEMA_VERSION}")
    if version != INDEX_SCHEMA_VERSION:
        return IndexCopy(artifact, None, "corrupt", "implementation index is not schema v2")
    if any(not isinstance(data.get(key), list) for key in ("plans", "events", "loose_commits")):
        return IndexCopy(artifact, None, "corrupt", "implementation index lists are malformed")
    for item in [*data["plans"], *data["events"], *data["loose_commits"]]:
        if not isinstance(item, dict):
            return IndexCopy(artifact, None, "corrupt", "implementation index contains a non-object item")
    return IndexCopy(artifact, data, "v2")


def _index_plan_id(raw: object) -> str:
    value = str(raw or "")
    if value.startswith(".ralph/plans/"):
        value = value.removeprefix(".ralph/plans/")
    return _plan_id_from_relative(value)


def _add_conflict(target: list[dict[str, str]], code: str, detail: str, *, path: str = "") -> None:
    target.append({"code": code, "path": path, "detail": _bounded(detail, 400)})


def _same_digest(artifacts: list[Artifact]) -> bool:
    values = {item.digest for item in artifacts if item.digest}
    return len(values) <= 1


def build_inventory(paths: StorePaths, *, active_root: Path | None = None, recovery_mode: bool = False) -> MigrationContext:
    active = (active_root or Path.cwd()).resolve()
    roots = _worktree_roots(paths.primary_root, active)
    artifacts, aliases = _scan_artifacts(roots, paths.primary_root.resolve())
    conflicts: list[dict[str, str]] = []
    corrupt: list[dict[str, str]] = []
    future: list[dict[str, str]] = []
    missing: list[str] = []
    orphan_views: list[str] = []
    warnings: list[str] = []
    plans: dict[str, PlanMigration] = {}

    for artifact in artifacts:
        if artifact.kind != "plan-markdown":
            continue
        try:
            plan_id = _plan_id_from_relative(artifact.relative)
        except (StorePathError, ValueError) as exc:
            _add_conflict(conflicts, "invalid_plan_id", str(exc), path=str(artifact.path))
            continue
        record = _plan_record(plans, plan_id)
        if artifact.alias_reason:
            continue
        try:
            text = _read_text(artifact)
            metadata, approved = _plan_metadata(text)
            record.plan_copies.append(PlanCopy(artifact, plan_id, approved, metadata, artifact.digest, content_signature=_plan_content_signature(text)))
        except MigrationError as exc:
            record.plan_copies.append(PlanCopy(artifact, plan_id, False, {}, artifact.digest, exc.message))
            _add_conflict(conflicts, exc.code, exc.message, path=str(artifact.path))

    for artifact in artifacts:
        if artifact.kind != "notes-html":
            continue
        try:
            plan_id = _plan_id_from_relative(artifact.relative[: -len(LEGACY_NOTE_SUFFIX)])
        except (StorePathError, ValueError) as exc:
            _add_conflict(conflicts, "invalid_plan_id", str(exc), path=str(artifact.path))
            continue
        record = _plan_record(plans, plan_id)
        record.note_copies.append(artifact)

    indexes: list[IndexCopy] = []
    for artifact in artifacts:
        if artifact.kind == "index-json":
            index = _parse_index(artifact)
            indexes.append(index)
            if index.schema == "corrupt":
                _add_conflict(corrupt, "corrupt_index", index.error, path=str(artifact.path))
            elif index.schema == "future":
                _add_conflict(future, "future_index", index.error, path=str(artifact.path))
        elif artifact.kind == "index-json-corrupt-copy":
            _add_conflict(corrupt, "quarantined_corrupt_index", "corrupt index evidence is present", path=str(artifact.path))

    # Select one plan and one notes source only after all copies have been
    # inventoried.  Identical worktree copies are compatible; divergent
    # copies remain evidence and block apply unless recovery mode is explicit.
    for record in plans.values():
        if record.plan_copies:
            primary_copy = next((item for item in record.plan_copies if item.artifact.root == paths.primary_root.resolve()), None)
            selected = primary_copy or sorted(record.plan_copies, key=lambda item: str(item.artifact.path))[0]
            record.plan_source = selected.artifact
            record.approved = any(item.approved for item in record.plan_copies)
            if len({item.content_signature for item in record.plan_copies if item.content_signature}) > 1:
                _add_conflict(record.conflicts, "divergent_plan_copies", "plan copies differ across worktrees", path=record.plan_id)
            if selected.error:
                _add_conflict(record.conflicts, "invalid_plan", selected.error, path=str(selected.artifact.path))
        if record.note_copies:
            primary_note = next((item for item in record.note_copies if item.root == paths.primary_root.resolve()), None)
            selected_note = primary_note or sorted(record.note_copies, key=lambda item: str(item.path))[0]
            record.selected_note = selected_note
            if not _same_digest(record.note_copies):
                _add_conflict(record.conflicts, "divergent_notes_copies", "per-plan HTML copies differ across worktrees", path=record.plan_id)
            if record.plan_source is None:
                missing.append(record.plan_id)
                _add_conflict(record.conflicts, "missing_plan", "notes evidence has no matching plan file", path=record.plan_id)
            elif not record.approved:
                _add_conflict(record.conflicts, "unapproved_plan", "notes evidence is not tied to an approved plan", path=record.plan_id)
            if not selected_note.alias_reason:
                try:
                    record.parsed_note = _parse_notes_once(selected_note, record.plan_id)
                except MigrationError as exc:
                    _add_conflict(record.conflicts, exc.code, exc.message, path=str(selected_note.path))
            if len(record.note_copies) > 1 and _same_digest(record.note_copies):
                warnings.append(f"identical worktree notes copies merged for {record.plan_id}")
        elif record.plan_source is not None and record.approved:
            warnings.append(f"approved plan has no legacy HTML notes: {record.plan_id}")

    index_events: list[dict[str, Any]] = []
    loose_commits: list[dict[str, Any]] = []
    loose_sources: list[dict[str, Any]] = []
    seen_index_events: dict[str, str] = {}
    seen_index_plans: dict[str, str] = {}
    seen_loose: dict[str, str] = {}

    def add_loose(entry: Mapping[str, Any], source: IndexCopy) -> None:
        commit = str(entry.get("commit", ""))
        material = digest(
            {
                "commit": commit,
                "branch": str(entry.get("branch", "")),
                "reason": str(entry.get("reason", "")),
                "notes": str(entry.get("notes", "")),
            }
        )
        if commit in seen_loose:
            if seen_loose[commit] != material:
                _add_conflict(conflicts, "divergent_loose_commit", "loose commit copies carry different material fields", path=commit)
            return
        seen_loose[commit] = material
        loose_commits.append({"entry": dict(entry), "source": source})
        loose_sources.append({"path": str(source.artifact.path), "commit": commit, "digest": material})

    for index in indexes:
        if index.data is None:
            continue
        data = index.data
        for plan_entry in data.get("plans", []):
            try:
                plan_id = _index_plan_id(plan_entry.get("plan"))
            except (StorePathError, ValueError, KeyError) as exc:
                _add_conflict(conflicts, "invalid_index_plan", str(exc), path=str(index.artifact.path))
                continue
            record = _plan_record(plans, plan_id)
            plan_signature = digest(plan_entry)
            if plan_id in seen_index_plans and seen_index_plans[plan_id] != plan_signature:
                _add_conflict(conflicts, "divergent_index_plan", "index plan entries carry different payloads", path=plan_id)
            seen_index_plans[plan_id] = plan_signature
            if record.plan_source is None:
                missing.append(plan_id)
                _add_conflict(record.conflicts, "missing_plan", "index plan entry has no matching plan file", path=plan_id)
            elif str(plan_entry.get("status", "")).strip().lower() in {"approved", "implemented", "active"} and not record.approved:
                _add_conflict(record.conflicts, "unapproved_plan", "index plan entry is not backed by an approved plan", path=plan_id)
        for event in data.get("events", []):
            if not _index_event_checksum_ok(event):
                _add_conflict(conflicts, "bad_checksum", "index event_id checksum does not match the event", path=str(index.artifact.path))
                continue
            event_id = str(event.get("event_id", ""))
            signature = digest(event)
            event_key = event_id or signature
            if event_key in seen_index_events:
                if seen_index_events[event_key] != signature:
                    _add_conflict(conflicts, "divergent_index_event", "index event IDs carry different payloads", path=event_key)
                continue
            seen_index_events[event_key] = signature
            if event.get("event") == "loose_commit_recorded":
                loose_entry = {
                    "type": "loose_commit",
                    "commit": event.get("commit", ""),
                    "branch": event.get("branch", ""),
                    "reason": event.get("reason", ""),
                    "notes": event.get("notes_detail", ""),
                    "created_at": event.get("created_at", ""),
                    "updated_at": event.get("timestamp") or event.get("created_at", ""),
                }
                add_loose(loose_entry, index)
            index_events.append({"event": event, "source": index})
        for loose in data.get("loose_commits", []):
            add_loose(loose, index)

    # Event specs are built after the plan and index inventory is complete so
    # index-only events can be attached to nested/worktree plans.
    for record in plans.values():
        if not record.parsed_note:
            continue
        try:
            start = _spec_from_initial(record.parsed_note, plan_rel=record.plan_rel, plan_root=paths.primary_root, approved=record.approved)
            specs = [start]
            provenance = _provenance_from_note(record.parsed_note, record.selected_note.root if record.selected_note else paths.primary_root)
            for ordinal, entry in enumerate(record.parsed_note.entries, start=1):
                specs.append(_spec_from_entry(entry, note=record.parsed_note, ordinal=ordinal, provenance=provenance))
            seen_operations: dict[str, EventSpec] = {}
            for spec in specs:
                if spec.operation_id in seen_operations:
                    _add_conflict(record.conflicts, "duplicate_operation_id", "legacy HTML contains a duplicate operation ID", path=spec.operation_id)
                seen_operations[spec.operation_id] = spec
            record.events = specs
        except MigrationError as exc:
            _add_conflict(record.conflicts, exc.code, exc.message, path=record.plan_id)

    for item in index_events:
        event = item["event"]
        source: IndexCopy = item["source"]
        raw_plan = str(event.get("plan", ""))
        if not raw_plan:
            if event.get("event") != "loose_commit_recorded":
                _add_conflict(conflicts, "orphan_index_event", "index event has no plan", path=str(source.artifact.path))
            continue
        try:
            plan_id = _index_plan_id(raw_plan)
        except (StorePathError, ValueError) as exc:
            _add_conflict(conflicts, "invalid_index_event_plan", str(exc), path=str(source.artifact.path))
            continue
        record = _plan_record(plans, plan_id)
        if event.get("event") == "notes_created":
            # The HTML template or the synthetic plan-only start below owns
            # the canonical started event; the index row is discovery metadata.
            continue
        try:
            spec = _spec_from_index(event, plan_id=plan_id, source=source)
        except MigrationError as exc:
            _add_conflict(record.conflicts, exc.code, exc.message, path=str(source.artifact.path))
            continue
        existing = next((candidate for candidate in record.events if candidate.operation_id == spec.operation_id), None)
        if existing is not None:
            matching_entry = None
            if record.parsed_note is not None:
                matching_entry = next(
                    (
                        candidate
                        for candidate in record.parsed_note.entries
                        if str(candidate.fields.get("Operation ID", "")) == spec.operation_id
                    ),
                    None,
                )
            compatible = existing.summary == spec.summary or (
                bool(event.get("notes_entry_hash"))
                and matching_entry is not None
                and str(event.get("notes_entry_hash")) == _entry_hash(matching_entry)
            )
            if not compatible:
                _add_conflict(record.conflicts, "divergent_operation", "index event conflicts with HTML event", path=spec.operation_id)
            elif spec.source == "legacy-index" and any(
                (spec.provenance.get("git") or {}).get(field)
                for field in ("branch", "commit", "workspace_instance_id")
            ):
                record.events = [replace(candidate, provenance=spec.provenance) if candidate.operation_id == spec.operation_id else candidate for candidate in record.events]
            continue
        record.events.append(spec)

    for record in plans.values():
        if record.events:
            if record.events[0].kind != "started" and record.plan_source is not None:
                record.events.insert(0, _synthetic_plan_event(record, paths))
            start = record.events[0]
            rest = sorted(record.events[1:], key=lambda spec: (_timestamp_sort_key(spec.timestamp), spec.source, spec.operation_id))
            record.events = [start, *rest]
        if len(record.events) > MAX_EVENTS_PER_PLAN:
            _add_conflict(record.conflicts, "event_limit", "plan exceeds migration event limit", path=record.plan_id)
        conflicts.extend({**item, "path": item.get("path") or record.plan_id} for item in record.conflicts)

    # Markdown and consolidated views are derived evidence.  A view with no
    # corresponding source is an orphan and blocks default apply.
    by_root_kind = {(item.root, item.kind) for item in artifacts if not item.alias_reason}
    for artifact in artifacts:
        if artifact.kind == "index-markdown" and (artifact.root, "index-json") not in by_root_kind:
            orphan_views.append(str(artifact.path))
        if artifact.kind in {"consolidated-html", "consolidated-markdown"} and not any(record.note_copies for record in plans.values()):
            orphan_views.append(str(artifact.path))

    # De-duplicate report lists while preserving deterministic order.
    missing = sorted(set(missing))
    orphan_views = sorted(set(orphan_views))
    return MigrationContext(
        paths=paths,
        active_root=active,
        recovery_mode=recovery_mode,
        roots=roots,
        artifacts=artifacts,
        plans=dict(sorted(plans.items())),
        indexes=indexes,
        index_events=index_events,
        loose_commits=loose_commits,
        conflicts=conflicts,
        aliases=aliases,
        corrupt_schemas=corrupt,
        future_schemas=future,
        missing_plans=missing,
        orphan_views=orphan_views,
        warnings=warnings,
        loose_sources=loose_sources,
    )


def _timestamp_sort_key(value: str) -> tuple[int, str]:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return (1, parsed.astimezone(UTC).isoformat())
    except (TypeError, ValueError):
        return (0, value)


def _state_updates(state: Mapping[str, Any], spec: EventSpec) -> dict[str, Any]:
    updates: dict[str, Any] = {"status": spec.status}
    if spec.phase:
        updates["phase"] = spec.phase
    if spec.kind in {"decision", "deviation", "migration_imported"} and spec.summary:
        updates["latest_decision"] = {"event_id": "pending", "summary": spec.summary}
    if spec.kind == "question_opened" and spec.summary:
        values = list(state.get("open_questions") or [])
        if spec.summary not in values:
            values.append(spec.summary)
        updates["open_questions"] = values[-8:]
    elif spec.kind == "question_resolved":
        updates["open_questions"] = [value for value in state.get("open_questions", []) if value != spec.summary]
    elif spec.kind == "blocker_opened" and spec.summary:
        values = list(state.get("open_blockers") or [])
        if spec.summary not in values:
            values.append(spec.summary)
        updates["open_blockers"] = values[-8:]
    elif spec.kind == "blocker_resolved":
        updates["open_blockers"] = [value for value in state.get("open_blockers", []) if value != spec.summary]
    elif spec.kind == "validation_changed":
        validation = dict(state.get("validation") or {})
        gate = "legacy-" + hashlib.sha256(spec.operation_id.encode("utf-8")).hexdigest()[:8]
        raw_result = next(
            (code.removeprefix("legacy-status-") for code in spec.evidence_codes if code.startswith("legacy-status-")),
            "",
        )
        result_map = {
            "pass": "pass",
            "passed": "pass",
            "validated": "pass",
            "complete": "pass",
            "completed": "pass",
            "fail": "fail",
            "failed": "fail",
            "partial": "partial",
            "blocked": "blocked",
            "not-run": "not_run",
            "not_run": "not_run",
            "pending": "pending",
        }
        validation[gate] = result_map.get(raw_result, _normalize_result(spec.status))
        updates["validation"] = validation
    return updates


def _synthetic_plan_event(record: PlanMigration, paths: StorePaths) -> EventSpec:
    source = record.plan_source
    if source is None:
        raise MigrationError("missing_plan", "cannot synthesize a plan without a plan source")
    timestamp = datetime.fromtimestamp(source.mtime_ns / 1_000_000_000, tz=UTC).replace(microsecond=0).isoformat()
    return EventSpec(
        plan_id=record.plan_id,
        kind="started",
        operation_id="mig-start-" + hashlib.sha256(record.plan_id.encode("utf-8")).hexdigest()[:40],
        timestamp=timestamp,
        summary="Plan registered",
        reason="No legacy HTML template was present",
        next_action="",
        references=(),
        status="active",
        phase="",
        category="synthetic",
        evidence_codes=("legacy-plan-only",),
        provenance=_git_provenance(source.root),
        source="legacy-plan",
        source_digest=source.digest,
    )


def _inventory_plan_payload(record: PlanMigration, paths: StorePaths) -> dict[str, Any]:
    legacy_bytes = sum(item.bytes for item in record.note_copies)
    new_state_bytes = 0
    expected_specs = list(record.events)
    if not expected_specs and record.plan_source is not None and record.approved:
        expected_specs = [_synthetic_plan_event(record, paths)]
    if expected_specs:
        start = expected_specs[0]
        initial = new_state(
            record.plan_id,
            plan_path=record.plan_rel,
            now=start.timestamp,
            status=start.status,
            objective=record.plan_id,
            phase=start.phase,
            next_action=start.next_action,
            **start.provenance,
        )
        state = initial
        for spec in expected_specs:
            state = dict(state)
            state.update(_state_updates(state, spec))
            state["semantic_hash"] = ""
            state["updated_at"] = spec.timestamp
            state["generation"] = int(state.get("generation", 0)) + 1
            state = validate_state(state, expected_plan_id=record.plan_id)
        new_state_bytes = encoded_size(state)
    return {
        "plan_id": record.plan_id,
        "plan_path": record.plan_rel,
        "approved": record.approved,
        "plan_copies": [
            {"path": str(item.artifact.path), "digest": item.digest, "approved": item.approved, "location": "primary" if item.artifact.root == paths.primary_root.resolve() else "worktree"}
            for item in record.plan_copies
        ],
        "notes_copies": [item.snapshot() for item in record.note_copies],
        "selected_note": str(record.selected_note.path) if record.selected_note else "",
        "schema": "v1-legacy-html" if record.parsed_note else "missing",
        "legacy_entry_count": len(record.parsed_note.entries) if record.parsed_note else 0,
        "expected_event_count": len(expected_specs),
        "expected_operation_ids": [spec.operation_id for spec in expected_specs],
        "expected_state_bytes": new_state_bytes,
        "legacy_bytes": legacy_bytes,
        "state_reduction_bytes": legacy_bytes - new_state_bytes,
        "warnings": sorted(record.warnings),
        "conflicts": sorted(record.conflicts, key=lambda item: (item.get("code", ""), item.get("path", ""))),
    }


def inventory_payload(context: MigrationContext) -> dict[str, Any]:
    files = [artifact.snapshot() for artifact in context.artifacts]
    index_payload = []
    index_plan_count = 0
    index_event_count = 0
    index_loose_count = 0
    for index in context.indexes:
        plan_count = len(index.data.get("plans", [])) if index.data else 0
        event_count = len(index.data.get("events", [])) if index.data else 0
        loose_count = len(index.data.get("loose_commits", [])) if index.data else 0
        index_plan_count += plan_count
        index_event_count += event_count
        index_loose_count += loose_count
        index_payload.append(
            {
                **index.artifact.snapshot(),
                "schema": index.schema,
                "error": index.error,
                "plans": plan_count,
                "events": event_count,
                "loose_commits": loose_count,
            }
        )
    expected_plans = [record for record in context.plans.values() if record.approved]
    warnings = sorted(set(context.warnings + [warning for record in context.plans.values() for warning in record.warnings]))
    payload = {
        "schema_version": 1,
        "command": "migrate-legacy",
        "mode": "inventory",
        "canonical_repo_root": str(context.paths.primary_root),
        "active_worktree_root": str(context.active_root),
        "recovery_mode": context.recovery_mode,
        "worktree_roots": [str(root) for root in context.roots],
        "approved_plans": [record.plan_id for record in expected_plans],
        "plan_count": len(expected_plans),
        "expected_new_plan_ids": sorted(record.plan_id for record in expected_plans),
        "expected_event_counts": {
            record.plan_id: int(record.events and len(record.events) or (1 if record.plan_source is not None else 0))
            for record in expected_plans
        },
        "expected_state_reductions": [_inventory_plan_payload(record, context.paths) for record in expected_plans],
        "files": files,
        "file_count": len(files),
        "notes_html": [item.snapshot() for item in context.artifacts if item.kind == "notes-html"],
        "index_sources": index_payload,
        "index_source_totals": {
            "plans": index_plan_count,
            "events": index_event_count,
            "loose_commits": index_loose_count,
        },
        "index_markdown": [item.snapshot() for item in context.artifacts if item.kind == "index-markdown"],
        "consolidated_views": [item.snapshot() for item in context.artifacts if item.kind.startswith("consolidated-")],
        "index_event_count": len(context.index_events),
        "loose_commit_count": len(context.loose_commits),
        "loose_commits": context.loose_sources,
        "conflicts": sorted(context.conflicts, key=lambda item: (item.get("code", ""), item.get("path", ""))),
        "aliases": sorted(context.aliases, key=lambda item: item.get("path", "")),
        "corrupt_schemas": sorted(context.corrupt_schemas, key=lambda item: (item.get("path", ""), item.get("detail", ""))),
        "future_schemas": sorted(context.future_schemas, key=lambda item: (item.get("path", ""), item.get("detail", ""))),
        "missing_plans": sorted(set(context.missing_plans)),
        "orphan_views": sorted(set(context.orphan_views)),
        "warnings": warnings,
        "blocked": context.blocked,
    }
    payload["source_digest"] = digest({key: value for key, value in payload.items() if key not in {"source_digest", "mode"}})
    return payload


def _source_snapshot(context: MigrationContext) -> dict[str, tuple[str, int, int]]:
    snapshot: dict[str, tuple[str, int, int]] = {}
    for artifact in context.artifacts:
        if artifact.alias_reason:
            continue
        snapshot[str(artifact.path)] = (artifact.digest, artifact.bytes, artifact.mtime_ns)
    return snapshot


def _verify_source_snapshot(context: MigrationContext, before: Mapping[str, tuple[str, int, int]]) -> None:
    for raw_path, expected in before.items():
        path = Path(raw_path)
        try:
            raw, info = _read_bounded_file(path, max_bytes=MAX_FILE_BYTES, expected_digest=expected[0])
            actual = (_digest_bytes(raw), int(info.st_size), int(info.st_mtime_ns))
        except OSError as exc:
            raise MigrationError("legacy_changed", "legacy source disappeared during migration") from exc
        if actual != expected:
            raise MigrationError("legacy_changed", "legacy source bytes or mtime changed during migration")


def _ensure_started(store: ImplementationStore, record: PlanMigration, spec: EventSpec, *, objective: str) -> StoreResult:
    plan_id = record.plan_id
    try:
        return store.register_plan(
            plan_id,
            plan_path=record.plan_rel,
            operation_id=spec.operation_id,
            now=spec.timestamp,
            provenance=spec.provenance,
            objective=objective,
            phase=spec.phase,
            next_action=spec.next_action,
            status=spec.status,
            summary=spec.summary,
            reason=spec.reason,
            references=list(spec.references),
            evidence_codes=list(spec.evidence_codes),
        )
    except StoreError as exc:
        if "already registered" not in str(exc):
            raise
        state = store.read_state(plan_id)
        events = store.read_events(plan_id)
        existing = next((event for event in events if event.get("operation_id") == spec.operation_id), None)
        if existing is None:
            raise MigrationError("existing_plan_conflict", "canonical plan exists with a different migration identity") from exc
        if existing.get("timestamp") != spec.timestamp or existing.get("summary") != spec.summary:
            raise MigrationError("idempotency_conflict", "started operation ID has a different payload")
        return StoreResult(False, spec.operation_id, existing.get("event_id", ""), state=state, reason="idempotent retry")


def _apply_plan_events(store: ImplementationStore, record: PlanMigration, specs: list[EventSpec]) -> int:
    if not specs:
        return 0
    objective = record.plan_id
    if record.plan_source and not record.plan_source.alias_reason:
        try:
            text = _read_text(record.plan_source)
            for line in text.splitlines():
                if line.strip().startswith("# "):
                    objective = _bounded(line.strip()[2:], 480)
                    break
        except (OSError, UnicodeError):
            pass
    started_result = _ensure_started(store, record, specs[0], objective=objective)
    imported = int(started_result.changed)
    for spec in specs[1:]:
        state = store.read_state(record.plan_id)
        if state is None:
            raise MigrationError("migration_failed", "plan state disappeared during migration")
        updates = _state_updates(state, spec)
        result = store.record_event(
            record.plan_id,
            kind=spec.kind,
            operation_id=spec.operation_id,
            summary=spec.summary,
            reason=spec.reason,
            next_action=spec.next_action,
            references=list(spec.references),
            evidence_codes=list(spec.evidence_codes),
            state_update=updates,
            now=spec.timestamp,
            provenance=spec.provenance,
        )
        imported += int(result.changed)
    return imported


def _loose_spec(item: Mapping[str, Any], context: MigrationContext, ordinal: int) -> tuple[str, str, list[str], dict[str, Any], str]:
    entry = item["entry"]
    source: IndexCopy = item["source"]
    commit = _bounded(str(entry.get("commit", "")), 80)
    if not commit or not COMMIT_RE.fullmatch(commit):
        raise MigrationError("legacy_invalid", "loose commit is not a valid Git SHA")
    reason = _bounded(str(entry.get("reason", "")), MAX_REASON)
    notes = _bounded(str(entry.get("notes", "")), MAX_REASON)
    summary = reason or notes or f"Loose commit {commit}"
    operation = "mig-loose-" + hashlib.sha256((source.artifact.digest + "\n" + canonical_json(entry) + "\n" + str(ordinal)).encode()).hexdigest()[:40]
    timestamp = _timestamp(str(entry.get("updated_at") or entry.get("created_at") or ""), datetime.fromtimestamp(source.artifact.mtime_ns / 1_000_000_000, tz=UTC).replace(microsecond=0).isoformat())
    provenance = _git_provenance(
        source.artifact.root,
        branch=str(entry.get("branch", "")),
        commit=commit,
        session=str(entry.get("session_id", "")),
        workspace=str(entry.get("workspace_instance_id", "")),
    )
    return operation, summary, [], provenance, timestamp


def apply_migration(context: MigrationContext, *, recovery_mode: bool = False) -> dict[str, Any]:
    if context.blocked and not recovery_mode:
        report = inventory_payload(context)
        raise MigrationError("migration_blocked", "legacy migration is blocked by unresolved evidence", report=report)
    # ``migration.lock`` is a canonical maintenance lock.  The public store
    # operations still take each plan's state.lock and the manifest lock for
    # their own transactions, but this outer lock prevents two migration
    # runs from interleaving their inventories and retries.
    ensure_store_layout(context.paths)
    with locked_file(context.paths.root / "migration.lock"):
        before = _source_snapshot(context)
        # Revalidate the inventory after taking the maintenance lock and
        # before the first canonical write.  A changed source now fails before
        # a partial import can be published; the post-write check below still
        # detects a race that occurs during the import itself.
        _verify_source_snapshot(context, before)
        store = ImplementationStore(context.paths)
        imported_plans = 0
        imported_events = 0
        skipped: list[dict[str, str]] = []
        loose_operations: list[str] = []

        for record in context.plans.values():
            if not record.approved:
                if record.events or record.note_copies:
                    if recovery_mode:
                        skipped.append({"plan_id": record.plan_id, "reason": "unapproved-or-conflicted"})
                        continue
                    raise MigrationError("migration_blocked", "unapproved legacy evidence remains", report=inventory_payload(context))
                # A plan-only document has no material legacy evidence to
                # merge; registering it keeps discovery complete while leaving
                # the approval decision untouched in the new state.
                if record.plan_source is None:
                    continue
            specs = list(record.events)
            if not specs:
                specs = [_synthetic_plan_event(record, context.paths)]
            imported_plans += int(store.read_state(record.plan_id) is None)
            imported_events += _apply_plan_events(store, record, specs)

        for ordinal, item in enumerate(context.loose_commits, start=1):
            operation, summary, references, provenance, timestamp = _loose_spec(item, context, ordinal)
            loose_operations.append(operation)
            result = store.append_unplanned_commit(
                operation_id=operation,
                summary=summary,
                references=references,
                now=timestamp,
                provenance=provenance,
            )
            imported_events += int(result.changed)

        # Re-publish every pointer after all plan events, including plans whose
        # status did not change during a retry.  This is a derived discovery
        # write, never a legacy evidence write.
        for record in context.plans.values():
            if not record.approved:
                continue
            state = store.read_state(record.plan_id)
            if state is not None:
                store._publish_manifest_pointer(state, force=True)  # noqa: SLF001 - maintenance boundary owns the manifest.

        _verify_source_snapshot(context, before)
        verification: list[dict[str, Any]] = []
        skipped_ids = {item["plan_id"] for item in skipped}
        for record in context.plans.values():
            if not record.approved or record.plan_id in skipped_ids:
                continue
            state = store.read_state(record.plan_id)
            events = store.read_events(record.plan_id)
            if state is None:
                raise MigrationError("verification_failed", "migrated plan has no state snapshot")
            expected = record.events or [_synthetic_plan_event(record, context.paths)]
            expected_ops = [item.operation_id for item in expected]
            actual_ops = [str(item.get("operation_id", "")) for item in events]
            if len(events) < len(expected) or actual_ops[: len(expected_ops)] != expected_ops:
                raise MigrationError("verification_failed", "migrated operation ordering or count does not match the inventory")
            actual_by_operation = {str(item.get("operation_id", "")): item for item in events}
            for expected_spec in expected:
                actual = actual_by_operation.get(expected_spec.operation_id)
                if actual is None:
                    raise MigrationError("verification_failed", "migrated operation ID is missing from the journal")
                if actual.get("record_hash") != event_record_hash(actual):
                    raise MigrationError("verification_failed", "migrated journal record hash does not verify")
                expected_git = expected_spec.provenance.get("git") or {}
                actual_git = actual.get("git") or {}
                for field in ("branch", "commit", "workspace_instance_id"):
                    if expected_git.get(field) and actual_git.get(field) != expected_git.get(field):
                        raise MigrationError("verification_failed", "migrated Git provenance does not match the source")
                if expected_spec.provenance.get("writer_session_id") and actual.get("writer_session_id") != expected_spec.provenance.get("writer_session_id"):
                    raise MigrationError("verification_failed", "migrated session provenance does not match the source")
                for field in ("kind", "timestamp", "summary", "reason", "next_action", "status"):
                    if str(actual.get(field, "")) != str(getattr(expected_spec, field)):
                        raise MigrationError("verification_failed", "migrated material fields do not match the source")
                if tuple(actual.get("references", [])) != tuple(expected_spec.references):
                    raise MigrationError("verification_failed", "migrated references do not match the source")
                if tuple(actual.get("evidence_codes", [])) != tuple(expected_spec.evidence_codes):
                    raise MigrationError("verification_failed", "migrated category or evidence codes do not match the source")
            if state.get("last_event_sequence") != len(events) or state.get("last_event_hash") != events[-1].get("record_hash"):
                raise MigrationError("verification_failed", "migrated state cursor does not match the journal")
            latest = events[-1]
            latest_expected = expected[-1]
            if any(
                str(latest.get(field, "")) != str(getattr(latest_expected, field))
                for field in ("kind", "timestamp", "summary", "operation_id", "status")
            ):
                raise MigrationError("verification_failed", "migrated latest material fields do not match the source")
            verification.append(
                {
                    "plan_id": record.plan_id,
                    "expected_event_count": len(expected),
                    "event_count": len(events),
                    "operation_ids": actual_ops,
                    "record_hashes": [str(item.get("record_hash", "")) for item in events],
                    "status": state.get("status", ""),
                    "branch": (state.get("git") or {}).get("branch", ""),
                    "commit": (state.get("git") or {}).get("commit", ""),
                    "session_id": state.get("writer_session_id", ""),
                    "workspace_instance_id": (state.get("git") or {}).get("workspace_instance_id", ""),
                    "semantic_hash": state.get("semantic_hash", ""),
                    "latest_material": {
                        "kind": latest.get("kind", ""),
                        "category": _legacy_category(str(latest.get("kind", "")), latest.get("evidence_codes", [])),
                        "timestamp": latest.get("timestamp", ""),
                        "summary": latest.get("summary", ""),
                        "reason": latest.get("reason", ""),
                        "impact": latest.get("next_action", ""),
                        "references": list(latest.get("references", [])),
                        "status": latest.get("status", ""),
                        "operation_id": latest.get("operation_id", ""),
                        "record_hash": latest.get("record_hash", ""),
                    },
                }
            )

        unplanned = store.read_unplanned_events()
        unplanned_by_operation = {str(item.get("operation_id", "")): item for item in unplanned}
        loose_verification: list[dict[str, Any]] = []
        for operation in loose_operations:
            event = unplanned_by_operation.get(operation)
            if event is None or event.get("record_hash") != event_record_hash(event):
                raise MigrationError("verification_failed", "migrated loose commit journal record is missing or corrupt")
            loose_verification.append(
                {
                    "operation_id": operation,
                    "record_hash": event.get("record_hash", ""),
                    "commit": (event.get("git") or {}).get("commit", ""),
                    "branch": (event.get("git") or {}).get("branch", ""),
                    "session_id": event.get("writer_session_id", ""),
                    "workspace_instance_id": (event.get("git") or {}).get("workspace_instance_id", ""),
                }
            )
        manifest = store.read_manifest()
        payload = inventory_payload(context)
        payload.update(
            {
                "mode": "apply",
                "recovery_mode": recovery_mode,
                "imported_plans": imported_plans,
                "imported_events": imported_events,
                "skipped": skipped,
                "verification": verification,
                "loose_verification": loose_verification,
                "manifest": manifest,
                "output_digest": digest({"verification": verification, "loose_verification": loose_verification, "manifest": manifest, "source_digest": payload["source_digest"]}),
            }
        )
        return payload


def _all_new_plans(store: ImplementationStore) -> list[tuple[str, dict[str, Any], tuple[dict[str, Any], ...]]]:
    plans_root = store.paths.plans_root
    if not plans_root.exists():
        return []
    try:
        root_info = plans_root.lstat()
    except OSError as exc:
        raise MigrationError("store_unavailable", "canonical plan directory cannot be inspected") from exc
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise MigrationError("store_alias", "canonical plan directory is an alias or non-directory")
    result: list[tuple[str, dict[str, Any], tuple[dict[str, Any], ...]]] = []
    pending = [plans_root]
    scanned = 0
    state_paths: list[Path] = []
    while pending:
        current = pending.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda entry: entry.name)
        except OSError as exc:
            raise MigrationError("store_unavailable", "canonical plan directory cannot be scanned") from exc
        for entry in entries:
            scanned += 1
            if scanned > MAX_SCANNED_ENTRIES:
                raise MigrationError("store_limit", "canonical plan directory exceeds the scan limit")
            path = Path(entry.path)
            if entry.is_symlink():
                raise MigrationError("store_alias", "canonical plan directory contains a symlink")
            if entry.is_dir(follow_symlinks=False):
                info = entry.stat(follow_symlinks=False)
                pending.append(path)
                continue
            if entry.name != "state.json":
                continue
            info = entry.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise MigrationError("store_alias", "canonical plan state is an alias or non-regular file")
            state_paths.append(path)
    for state_path in sorted(state_paths, key=lambda item: item.relative_to(plans_root).as_posix()):
        plan_root = state_path.parent
        try:
            plan_id = plan_root.relative_to(plans_root).as_posix()
            validate_plan_id(plan_id)
        except (StorePathError, ValueError) as exc:
            raise MigrationError("store_path", "canonical plan identifier is invalid") from exc
        state = store.read_state(plan_id)
        if state is None:
            continue
        result.append((plan_id, state, store.read_events(plan_id)))
    return result


def _legacy_category(kind: str, evidence_codes: Iterable[str] = ()) -> str:
    for code in evidence_codes:
        if code.startswith("legacy-category-"):
            value = code.removeprefix("legacy-category-")
            if value in ALLOWED_CATEGORIES:
                return value
    return {
        "decision": "decision",
        "deviation": "deviation",
        "question_opened": "open-question",
        "question_resolved": "open-question",
        "validation_changed": "validation",
        "completed": "summary",
        "reopened": "decision",
        "migration_imported": "summary",
        "started": "summary",
    }.get(kind, "decision")


def _render_legacy_html(plan_id: str, state: Mapping[str, Any], events: Iterable[Mapping[str, Any]]) -> str:
    events = tuple(events)
    categories = ("decision", "deviation", "tradeoff", "open-question", "validation", "summary")
    labels = {
        "decision": "Design Decisions",
        "deviation": "Deviations From Spec",
        "tradeoff": "Tradeoffs Considered",
        "open-question": "Open Questions",
        "validation": "Validation Notes",
        "summary": "Final Implementation Summary",
    }
    grouped: dict[str, list[str]] = {category: [] for category in categories}
    started = next((event for event in events if event.get("kind") == "started"), None)
    for event in events:
        if event.get("kind") == "started":
            continue
        category = _legacy_category(str(event.get("kind", "")), event.get("evidence_codes", []))
        refs = ", ".join(html.escape(str(value), quote=True) for value in event.get("references", [])) or "n/a"
        grouped[category].append(
            "    <article class=\"entry\" data-entry-kind=\"{category}\"><dl>"
            "<dt>Timestamp</dt><dd>{timestamp}</dd><dt>Category</dt><dd>{category}</dd>"
            "<dt>Decision</dt><dd>{summary}</dd><dt>Reason</dt><dd>{reason}</dd>"
            "<dt>Impact</dt><dd>{impact}</dd><dt>Related files</dt><dd>{refs}</dd>"
            "<dt>Status</dt><dd>{status}</dd><dt>Operation ID</dt><dd>{operation}</dd></dl></article>\n".format(
                category=html.escape(category, quote=True),
                timestamp=html.escape(str(event.get("timestamp", "")), quote=True),
                summary=html.escape(_bounded(event.get("summary", "")), quote=True) or "(none)",
                reason=html.escape(_bounded(event.get("reason", "")), quote=True) or "(none)",
                impact=html.escape(_bounded(event.get("next_action", "")), quote=True) or "(none)",
                refs=refs,
                status=html.escape(str(event.get("status", state.get("status", ""))), quote=True),
                operation=html.escape(str(event.get("operation_id", "")), quote=True),
            )
        )
    sections = []
    for category in categories:
        sections.append(
            f'    <section class="entry-section" data-entry-section="{category}"><h2>{labels[category]}</h2>\n'
            f"{''.join(grouped[category])}      <!-- IMPLEMENTATION_NOTES_{category.replace('-', '_').upper()}_ANCHOR -->\n    </section>"
        )
    timeline = ""
    if started is not None:
        refs = ", ".join(html.escape(str(value), quote=True) for value in started.get("references", [])) or "n/a"
        started_git = started.get("git") or {}
        provenance = (
            "<dl class=\"meta-grid\">"
            f"<dt>Git branch</dt><dd>{html.escape(str(started_git.get('branch', '')), quote=True)}</dd>"
            f"<dt>Git SHA</dt><dd>{html.escape(str(started_git.get('commit', '')), quote=True)}</dd>"
            f"<dt>Session id</dt><dd>{html.escape(str(started.get('writer_session_id', '')), quote=True)}</dd>"
            f"<dt>Workspace instance id</dt><dd>{html.escape(str(started_git.get('workspace_instance_id', '')), quote=True)}</dd>"
            "</dl>"
        )
        timeline = (
            f'    {provenance}<section aria-labelledby="timeline-heading"><h2 id="timeline-heading">Timeline</h2>'
            '<article class="entry" data-entry-kind="initial"><h3>Implementation Started</h3><dl>'
            f"<dt>Timestamp</dt><dd>{html.escape(str(started.get('timestamp', '')), quote=True)}</dd>"
            "<dt>Category</dt><dd>summary</dd>"
            f"<dt>Decision</dt><dd>{html.escape(_bounded(started.get('summary', '')), quote=True)}</dd>"
            f"<dt>Reason</dt><dd>{html.escape(_bounded(started.get('reason', '')), quote=True)}</dd>"
            f"<dt>Impact</dt><dd>{html.escape(_bounded(started.get('next_action', '')), quote=True)}</dd>"
            f"<dt>Related files</dt><dd>{refs}</dd>"
            f"<dt>Status</dt><dd>{html.escape(str(started.get('status', state.get('status', ''))), quote=True)}</dd>"
            f"<dt>Operation ID</dt><dd>{html.escape(str(started.get('operation_id', '')), quote=True)}</dd>"
            "</dl></article></section>\n"
        )
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        f"<title>Implementation Notes - {html.escape(plan_id)}</title></head><body>\n"
        f"<main data-implementation-notes=\"true\"><h1>Implementation Notes - {html.escape(plan_id)}</h1>\n"
        f"<p>Status: {html.escape(str(state.get('status', '')))}; phase: {html.escape(str(state.get('phase', '')))}</p>\n"
        f"{timeline}"
        f"{''.join(sections)}\n</main></body></html>\n"
    )


def _legacy_index_all(
    plans: list[tuple[str, Mapping[str, Any], tuple[Mapping[str, Any], ...]]],
    root: Path,
    unplanned: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    plan_rows = []
    events = []
    for plan_id, state, plan_events in plans:
        notes = f".ralph/plans/{plan_id}{LEGACY_NOTE_SUFFIX}"
        plan_rows.append(
            {
                "type": "plan",
                "plan": f".ralph/plans/{plan_id}.md",
                "notes": notes,
                "status": "implemented" if state.get("status") == "completed" else state.get("status", "planned"),
                "branch": (state.get("git") or {}).get("branch", ""),
                "commits": [value for value in [(state.get("git") or {}).get("commit", "")] if value],
                "pr": "",
                "session_id": state.get("writer_session_id", ""),
                "workspace_instance_id": (state.get("git") or {}).get("workspace_instance_id", ""),
                "created_at": state.get("created_at", ""),
                "updated_at": state.get("updated_at", ""),
            }
        )
        for event in plan_events:
            events.append(
                {
                    "event": "notes_created" if event.get("kind") == "started" else "note_appended",
                    "plan": f".ralph/plans/{plan_id}.md",
                    "notes": notes,
                    "status": event.get("status", ""),
                    "branch": (event.get("git") or {}).get("branch", ""),
                    "commit": (event.get("git") or {}).get("commit", ""),
                    "session_id": event.get("writer_session_id", ""),
                    "workspace_instance_id": (event.get("git") or {}).get("workspace_instance_id", ""),
                    "operation_id": event.get("operation_id", ""),
                    "timestamp": event.get("timestamp", ""),
                    "event_id": event.get("event_id", ""),
                    "kind": event.get("kind", ""),
                    "summary": _bounded(event.get("summary", "")),
                }
            )
    loose_commits = []
    for event in unplanned:
        commit = str((event.get("git") or {}).get("commit", ""))
        loose_commits.append(
            {
                "type": "loose_commit",
                "commit": commit,
                "branch": (event.get("git") or {}).get("branch", ""),
                "reason": event.get("reason", ""),
                "notes": event.get("summary", ""),
                "linked_plan": None,
                "created_at": event.get("timestamp", ""),
                "updated_at": event.get("timestamp", ""),
            }
        )
        events.append(
            {
                "event": "loose_commit_recorded",
                "plan": "",
                "notes": "",
                "status": "loose_commit",
                "branch": (event.get("git") or {}).get("branch", ""),
                "commit": commit,
                "session_id": event.get("writer_session_id", ""),
                "workspace_instance_id": (event.get("git") or {}).get("workspace_instance_id", ""),
                "operation_id": event.get("operation_id", ""),
                "timestamp": event.get("timestamp", ""),
                "event_id": event.get("event_id", ""),
                "kind": event.get("kind", ""),
                "reason": event.get("reason", ""),
                "notes_detail": event.get("summary", ""),
                "summary": _bounded(event.get("summary", "")),
            }
        )
    for event in events:
        material = {key: value for key, value in event.items() if key not in {"event_id", "created_at", "timestamp"}}
        event["event_id"] = hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()
    return {"version": 2, "canonical_repo_root": str(root), "plans": plan_rows, "loose_commits": loose_commits, "events": events}


def _render_index_markdown(index: Mapping[str, Any]) -> str:
    lines = ["# Implementation Index", "", f"Version: {index.get('version', 2)}", "", "## Plans", "", "| Plan | Status | Branch | Commits |", "| --- | --- | --- | --- |"]
    for plan in index.get("plans", []):
        lines.append(
            f"| {plan.get('plan', '')} | {plan.get('status', '')} | {plan.get('branch', '')} | {', '.join(plan.get('commits', [])) or '-'} |"
        )
    lines.extend(["", "## Implementation Events", ""])
    for event in index.get("events", []):
        lines.append(f"- [{event.get('timestamp', '')}] {event.get('kind', event.get('event', ''))}: {_bounded(event.get('summary', ''))} (operation {event.get('operation_id', '')})")
    return "\n".join(lines) + "\n"


def _render_consolidated_html(plans: list[tuple[str, Mapping[str, Any], tuple[Mapping[str, Any], ...]]]) -> str:
    items = []
    for plan_id, state, events in plans:
        for event in events:
            items.append(
                f"    <article class=\"entry\" data-plan-id=\"{html.escape(plan_id)}\"><h2>{html.escape(plan_id)}</h2>"
                f"<dl><dt>Timestamp</dt><dd>{html.escape(str(event.get('timestamp', '')))}</dd>"
                f"<dt>Category</dt><dd>{html.escape(_legacy_category(str(event.get('kind', '')), event.get('evidence_codes', [])))}</dd>"
                f"<dt>Decision</dt><dd>{html.escape(_bounded(event.get('summary', '')))}</dd>"
                f"<dt>Status</dt><dd>{html.escape(str(event.get('status', state.get('status', ''))))}</dd>"
                f"<dt>Operation ID</dt><dd>{html.escape(str(event.get('operation_id', '')))}</dd></dl></article>"
            )
    return "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\"><title>Consolidated Implementation Notes</title></head><body><main data-consolidated-implementation-notes=\"true\">\n" + "\n".join(items) + "\n</main></body></html>\n"


def _render_consolidated_markdown(plans: list[tuple[str, Mapping[str, Any], tuple[Mapping[str, Any], ...]]]) -> str:
    lines = ["# Consolidated Implementation Notes", "", "This deterministic view is rebuilt from the canonical journal and state.", ""]
    for plan_id, state, events in plans:
        lines.extend([f"## {plan_id}", "", f"- Status: `{state.get('status', '')}`", ""])
        for event in events:
            lines.append(f"- `{event.get('timestamp', '')}` `{_legacy_category(str(event.get('kind', '')), event.get('evidence_codes', []))}`: {_bounded(event.get('summary', ''))} (operation `{event.get('operation_id', '')}`)")
        lines.append("")
    return "\n".join(lines)


def rebuild_legacy_views(store: ImplementationStore, *, apply: bool = False, plan_id: str | None = None) -> dict[str, Any]:
    all_plans = _all_new_plans(store)
    plans = all_plans
    if plan_id:
        selected_id = plan_id
        if selected_id.startswith(".ralph/plans/"):
            selected_id = selected_id.removeprefix(".ralph/plans/")
        if selected_id.endswith(".md") or selected_id.endswith(".markdown"):
            selected_id = str(Path(selected_id).with_suffix(""))
        plans = [item for item in plans if item[0] == selected_id]
    if not plans:
        raise MigrationError("plan_not_registered", "canonical implementation store has no plans")
    views: list[tuple[Path, str]] = []
    for plan_id, state, events in plans:
        views.append((store.paths.primary_root / ".ralph" / "plans" / f"{plan_id}{LEGACY_NOTE_SUFFIX}", _render_legacy_html(plan_id, state, events)))
    unplanned = store.read_unplanned_events()
    # A selective rollback limits the per-plan note that is staged, but global
    # indexes and consolidated views describe the complete canonical store.
    # Rendering those artifacts from ``plans`` would silently delete every
    # unselected plan from the compatibility surface.
    index = _legacy_index_all(all_plans, store.paths.primary_root, unplanned)
    views.extend(
        [
            (store.paths.primary_root / ".ralph" / "plans" / INDEX_JSON_NAME, json.dumps(index, ensure_ascii=True, indent=2, sort_keys=True) + "\n"),
            (store.paths.primary_root / ".ralph" / "plans" / INDEX_MD_NAME, _render_index_markdown(index)),
            (store.paths.primary_root / ".ralph" / "plans" / CONSOLIDATED_HTML_NAME, _render_consolidated_html(all_plans)),
            (store.paths.primary_root / ".ralph" / "plans" / CONSOLIDATED_MD_NAME, _render_consolidated_markdown(all_plans)),
        ]
    )
    canonical_sources = {
        (store.paths.primary_root / ".ralph" / "plans" / f"{plan_id}.md").absolute()
        for plan_id, _state, _events in all_plans
    }
    canonical_sources.update(
        {
            (store.paths.primary_root / str(state.get("plan_path"))).absolute()
            for _plan_id, state, _events in all_plans
            if str(state.get("plan_path") or "").strip()
        }
    )
    for target, _content in views:
        if target.absolute() in canonical_sources:
            raise MigrationError(
                "rollback_source_overlap",
                "legacy rollback output overlaps a registered canonical plan source",
            )
    for _target, content in views:
        if len(content.encode("utf-8")) > MAX_DERIVED_VIEW_BYTES:
            raise MigrationError("rollback_limit", "legacy rollback view exceeds the bounded publication limit")
    source_digest = digest(
        {
            "plans": [{"plan_id": plan_id, "state": state, "events": list(events)} for plan_id, state, events in all_plans],
            "unplanned": list(unplanned),
        }
    )
    staged: list[tuple[Path, str, str]] = []
    view_content = {target: content for target, content in views}
    plans_dir = store.paths.primary_root / ".ralph" / "plans"
    try:
        _reject_symlink_components(plans_dir)
    except (OSError, StorePathError) as exc:
        raise MigrationError("rollback_target_alias", "legacy rollback plans directory is unsafe") from exc
    stage_dir = Path(tempfile.mkdtemp(prefix=".rollback-", dir=plans_dir))
    os.chmod(stage_dir, 0o700)
    try:
        for target, content in views:
            stage = stage_dir / target.relative_to(store.paths.primary_root / ".ralph" / "plans")
            stage.parent.mkdir(parents=True, exist_ok=True)
            _reject_symlink_components(stage.parent)
            encoded = content.encode("utf-8")
            fd = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                view = memoryview(encoded)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise OSError("short staged rollback write")
                    view = view[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
            staged.append((target, _digest_bytes(content.encode("utf-8")), str(stage)))
        # Validation occurs entirely against the temporary outputs before any
        # legacy target is replaced.
        for target, expected_digest, stage in staged:
            raw, _stat = _read_bounded_file(Path(stage), max_bytes=MAX_DERIVED_VIEW_BYTES)
            if _digest_bytes(raw) != expected_digest:
                raise MigrationError("rollback_validation_failed", "staged legacy view digest changed")
        output_digest = digest({str(target.relative_to(store.paths.primary_root)): digest_value for target, digest_value, _stage in staged})
        if apply:
            with locked_file(store.paths.manifest_lock):
                snapshots = [(target, _snapshot_rollback_target(target)) for target, _expected_digest, _stage in staged]
                applied: list[Path] = []
                try:
                    for target, _expected_digest, _stage in staged:
                        applied.append(target)
                        store.publish_compatibility_view(
                            target.relative_to(store.paths.primary_root),
                            view_content[target],
                            hard_limit=MAX_DERIVED_VIEW_BYTES,
                        )
                except (StorePathError, StoreIOError, OSError, ValueError) as exc:
                    try:
                        snapshot_by_target = dict(snapshots)
                        for target in reversed(applied):
                            _restore_rollback_target(target, snapshot_by_target[target])
                    except (OSError, StorePathError, StoreIOError, ValueError) as restore_exc:
                        raise MigrationError(
                            "rollback_restore_failed",
                            "legacy rollback failed and could not restore all prior views",
                        ) from restore_exc
                    raise MigrationError(
                        "rollback_publish_failed",
                        "legacy rollback publication failed; prior views were restored",
                    ) from exc
        return {
            "schema_version": 1,
            "command": "rebuild-legacy",
            "mode": "apply" if apply else "dry-run",
            "applied": apply,
            "plans": [plan_id for plan_id, _state, _events in plans],
            "outputs": [str(target.relative_to(store.paths.primary_root)) for target, _content in views],
            "source_digest": source_digest,
            "output_digest": output_digest,
            "view_digests": {str(target.relative_to(store.paths.primary_root)): digest_value for target, digest_value, _stage in staged},
        }
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)
