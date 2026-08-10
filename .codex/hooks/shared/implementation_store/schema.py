"""Bounded schemas and deterministic hashes for the implementation store."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any, Mapping

from ..redaction import is_red


CURRENT_SCHEMA_VERSION = 1
STATE_TARGET_BYTES = 2 * 1024
STATE_WARNING_BYTES = 6 * 1024
STATE_HARD_LIMIT_BYTES = 8 * 1024
MANIFEST_HARD_LIMIT_BYTES = 8 * 1024
EVENT_HARD_LIMIT_BYTES = 4 * 1024
UNPLANNED_EVENT_HARD_LIMIT_BYTES = 4 * 1024
CONTEXT_LEDGER_HARD_LIMIT_BYTES = 2 * 1024
# The record limits above bound individual values.  These additional limits
# bound the journals themselves so a long-running session cannot turn a
# read-only lookup or a CLI digest into an unbounded allocation.
PLAN_JOURNAL_MAX_BYTES = 8 * 1024 * 1024
PLAN_JOURNAL_MAX_RECORDS = 4096
UNPLANNED_JOURNAL_MAX_BYTES = 4 * 1024 * 1024
UNPLANNED_JOURNAL_MAX_RECORDS = 4096
CONTEXT_LEDGER_MAX_BYTES = 4 * 1024 * 1024
CONTEXT_LEDGER_MAX_RECORDS = 4096

VALID_STATUSES = frozenset({"planned", "active", "completed", "blocked", "superseded", "reopened"})
VALID_CLASSIFICATIONS = frozenset({"GREEN", "YELLOW"})
VALID_VALIDATION = frozenset({"not_run", "pending", "partial", "pass", "fail", "blocked"})
VALID_MODEL_FAMILIES = frozenset({"luna", "terra", "sol", "unknown"})
VALID_MODEL_SOURCES = frozenset({"payload", "environment", "repository-default", "unknown"})
VALID_CAPSULE_KINDS = frozenset({"full", "delta", "expanded"})
MATERIAL_EVENT_KINDS = frozenset(
    {
        "started",
        "phase_changed",
        "decision",
        "deviation",
        "blocker_opened",
        "blocker_resolved",
        "question_opened",
        "question_resolved",
        "validation_changed",
        "completed",
        "reopened",
        "migration_imported",
        "loose_commit_recorded",
    }
)

_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,95}$")
_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{7,64}$")

STATE_PATCH_KEYS = frozenset(
    {
        "plan_path",
        "status",
        "classification",
        "phase",
        "objective",
        "latest_decision",
        "next_action",
        "open_blockers",
        "open_questions",
        "validation",
        "active_files",
        "git",
        "model_family",
        "model_source",
        "model_verified",
        "origin",
        "intent",
    }
)


class SchemaError(ValueError):
    """Raised when a current-schema record is malformed or unbounded."""


class FutureSchemaError(SchemaError):
    """Raised for a newer schema; callers must not quarantine or downgrade it."""


class RedContentError(SchemaError):
    """Raised when a bounded field contains RED-sensitive content."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def encoded_size(value: Any) -> int:
    return len(canonical_json(value).encode("utf-8"))


def state_size_band(size: int) -> str:
    """Classify an encoded snapshot without changing the persisted schema."""

    if size <= STATE_TARGET_BYTES:
        return "target"
    if size < STATE_HARD_LIMIT_BYTES:
        return "warning"
    return "hard"


def validate_operation_id(value: str) -> str:
    return _identifier(value, "operation_id")


def validate_context_ledger_record(record: Mapping[str, Any], *, hard_limit: int = CONTEXT_LEDGER_HARD_LIMIT_BYTES) -> dict[str, Any]:
    """Validate one content-free exactly-once context emission record."""

    obj = _object(record, "context ledger record")
    _schema_version(obj, "context ledger record")
    _unknown_keys(
        obj,
        {
            "schema_version",
            "project_id",
            "workspace_instance_id",
            "session_id",
            "context_epoch",
            "plan_id",
            "progress_generation",
            "capsule_kind",
            "emission_id",
        },
        "context ledger record",
    )
    project_id = _identifier(obj.get("project_id", ""), "context ledger project_id")
    workspace_instance_id = _identifier(obj.get("workspace_instance_id", ""), "context ledger workspace_instance_id")
    session_id = _identifier(obj.get("session_id", ""), "context ledger session_id")
    context_epoch = _identifier(obj.get("context_epoch", ""), "context ledger context_epoch")
    plan_id = _plan_id(obj.get("plan_id"))
    progress_generation = _integer(obj.get("progress_generation", 0), "context ledger progress_generation", minimum=0)
    capsule_kind = _enum(obj.get("capsule_kind", ""), VALID_CAPSULE_KINDS, "context ledger capsule_kind")
    emission_id = _identifier(obj.get("emission_id", ""), "context ledger emission_id")
    normalized = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "project_id": project_id,
        "workspace_instance_id": workspace_instance_id,
        "session_id": session_id,
        "context_epoch": context_epoch,
        "plan_id": plan_id,
        "progress_generation": progress_generation,
        "capsule_kind": capsule_kind,
        "emission_id": emission_id,
    }
    _reject_red(normalized, "context ledger record")
    if encoded_size(normalized) + 1 > hard_limit:
        raise SchemaError(f"context ledger record exceeds hard limit of {hard_limit} UTF-8 bytes")
    return normalized


def context_ledger_key(record: Mapping[str, Any]) -> tuple[str, str, str, str, str, int, str]:
    """Return the stable deduplication key; no capsule content is included."""

    normalized = validate_context_ledger_record(record)
    return (
        normalized["project_id"],
        normalized["workspace_instance_id"],
        normalized["session_id"],
        normalized["context_epoch"],
        normalized["plan_id"],
        normalized["progress_generation"],
        normalized["capsule_kind"],
    )


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def state_semantic_hash(state: Mapping[str, Any]) -> str:
    """Hash lifecycle/model state while excluding observational metadata."""

    projection = deepcopy(dict(state))
    for key in (
        "semantic_hash",
        "generation",
        "last_operation_id",
        "last_event_sequence",
        "last_event_hash",
        "updated_at",
        "created_at",
        "writer_session_id",
        "writer_process_id",
    ):
        projection.pop(key, None)
    return digest(projection)


def validate_state(
    state: Mapping[str, Any],
    *,
    expected_plan_id: str | None = None,
    hard_limit: int = STATE_HARD_LIMIT_BYTES,
) -> dict[str, Any]:
    obj = _object(state, "state")
    _schema_version(obj, "state")
    allowed = {
        "schema_version",
        "plan_id",
        "plan_path",
        "generation",
        "semantic_hash",
        "status",
        "classification",
        "phase",
        "objective",
        "latest_decision",
        "next_action",
        "open_blockers",
        "open_questions",
        "validation",
        "active_files",
        "last_operation_id",
        "last_event_sequence",
        "last_event_hash",
        "git",
        "writer_session_id",
        "model_family",
        "model_source",
        "model_verified",
        "origin",
        "intent",
        "created_at",
        "updated_at",
    }
    _unknown_keys(obj, allowed, "state")
    plan_id = _plan_id(obj.get("plan_id"))
    if expected_plan_id is not None and plan_id != expected_plan_id:
        raise SchemaError("state plan_id does not match its directory")
    _repo_relative_path(obj.get("plan_path", ""), "plan_path", allow_empty=True)
    generation = _integer(obj.get("generation", 0), "generation", minimum=0)
    status = _enum(obj.get("status", "planned"), VALID_STATUSES, "status")
    classification = _enum(obj.get("classification", "GREEN"), VALID_CLASSIFICATIONS, "classification")
    phase = _text(obj.get("phase", ""), "phase", 160, allow_empty=True)
    objective = _text(obj.get("objective", ""), "objective", 480, allow_empty=True)
    next_action = _text(obj.get("next_action", ""), "next_action", 400, allow_empty=True)
    latest_decision = obj.get("latest_decision", None)
    if latest_decision is not None:
        latest_decision = _object(latest_decision, "latest_decision")
        _unknown_keys(latest_decision, {"event_id", "summary"}, "latest_decision")
        latest_decision = {
            "event_id": _identifier(latest_decision.get("event_id", ""), "latest_decision.event_id", allow_empty=True),
            "summary": _text(latest_decision.get("summary", ""), "latest_decision.summary", 400, allow_empty=True),
        }
    blockers = _text_list(obj.get("open_blockers", []), "open_blockers", max_items=8, max_length=400)
    questions = _text_list(obj.get("open_questions", []), "open_questions", max_items=8, max_length=400)
    validation = _validation(obj.get("validation", {}))
    active_files = _path_list(obj.get("active_files", []), "active_files", max_items=16, max_length=320)
    last_operation_id = _identifier(obj.get("last_operation_id", ""), "last_operation_id", allow_empty=True)
    last_event_sequence = _integer(obj.get("last_event_sequence", 0), "last_event_sequence", minimum=0)
    last_event_hash = _hash(obj.get("last_event_hash", ""), "last_event_hash", allow_empty=True)
    git = _git(obj.get("git", {}))
    writer_session_id = _identifier(obj.get("writer_session_id", ""), "writer_session_id", allow_empty=True)
    model_family = _enum(obj.get("model_family", "unknown"), VALID_MODEL_FAMILIES, "model_family")
    model_source = _enum(obj.get("model_source", "unknown"), VALID_MODEL_SOURCES, "model_source")
    model_verified = obj.get("model_verified", False)
    if not isinstance(model_verified, bool):
        raise SchemaError("model_verified must be boolean")
    origin = _text(obj.get("origin", "implementation-progress"), "origin", 80)
    intent = _text(obj.get("intent", "progress-maintenance"), "intent", 80)
    created_at = _timestamp(obj.get("created_at", ""), "created_at", allow_empty=True)
    updated_at = _timestamp(obj.get("updated_at", ""), "updated_at", allow_empty=True)
    supplied_semantic_hash = _hash(obj.get("semantic_hash", ""), "semantic_hash", allow_empty=True)
    normalized = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "plan_id": plan_id,
        "plan_path": obj.get("plan_path", ""),
        "generation": generation,
        "semantic_hash": "",
        "status": status,
        "classification": classification,
        "phase": phase,
        "objective": objective,
        "latest_decision": latest_decision,
        "next_action": next_action,
        "open_blockers": blockers,
        "open_questions": questions,
        "validation": validation,
        "active_files": active_files,
        "last_operation_id": last_operation_id,
        "last_event_sequence": last_event_sequence,
        "last_event_hash": last_event_hash,
        "git": git,
        "writer_session_id": writer_session_id,
        "model_family": model_family,
        "model_source": model_source,
        "model_verified": model_verified,
        "origin": origin,
        "intent": intent,
        "created_at": created_at,
        "updated_at": updated_at,
    }
    normalized["semantic_hash"] = state_semantic_hash(normalized)
    if supplied_semantic_hash and supplied_semantic_hash != normalized["semantic_hash"]:
        raise SchemaError("state semantic_hash does not match the state")
    _reject_red(normalized, "state")
    size = encoded_size(normalized)
    if size > hard_limit:
        raise SchemaError(f"state exceeds hard limit of {hard_limit} UTF-8 bytes")
    return normalized


def validate_event(
    event: Mapping[str, Any],
    *,
    expected_plan_id: str | None = None,
    unplanned: bool = False,
    hard_limit: int | None = None,
    allow_unhashed: bool = False,
) -> dict[str, Any]:
    obj = _object(event, "event")
    _schema_version(obj, "event")
    allowed = {
        "schema_version",
        "sequence",
        "event_id",
        "operation_id",
        "timestamp",
        "kind",
        "summary",
        "reason",
        "next_action",
        "status",
        "classification",
        "phase",
        "plan_id",
        "plan_path",
        "references",
        "evidence_codes",
        "git",
        "writer_session_id",
        "model_family",
        "model_source",
        "model_verified",
        "origin",
        "intent",
        "state_patch",
        "operation_payload_hash",
        "state_semantic_hash",
        "previous_event_hash",
        "record_hash",
    }
    _unknown_keys(obj, allowed, "event")
    sequence = _integer(obj.get("sequence", 0), "sequence", minimum=1)
    event_id = _identifier(obj.get("event_id"), "event_id")
    operation_id = _identifier(obj.get("operation_id"), "operation_id")
    timestamp = _timestamp(obj.get("timestamp"), "timestamp")
    kind = _enum(obj.get("kind"), MATERIAL_EVENT_KINDS, "kind")
    if unplanned and kind != "loose_commit_recorded":
        raise SchemaError("unplanned-events.jsonl accepts only loose_commit_recorded events")
    plan_id = _plan_id(obj.get("plan_id", ""), allow_empty=unplanned)
    if expected_plan_id is not None and plan_id != expected_plan_id:
        raise SchemaError("event plan_id does not match its journal")
    plan_path = _repo_relative_path(obj.get("plan_path", ""), "plan_path", allow_empty=True)
    summary = _text(obj.get("summary", ""), "summary", 400, allow_empty=True)
    reason = _text(obj.get("reason", ""), "reason", 400, allow_empty=True)
    next_action = _text(obj.get("next_action", ""), "next_action", 400, allow_empty=True)
    status = _enum(obj.get("status", "planned"), VALID_STATUSES, "status")
    classification = _enum(obj.get("classification", "GREEN"), VALID_CLASSIFICATIONS, "classification")
    phase = _text(obj.get("phase", ""), "phase", 160, allow_empty=True)
    references = _path_list(obj.get("references", []), "references", max_items=8, max_length=320)
    evidence_codes = _code_list(obj.get("evidence_codes", []), "evidence_codes", max_items=8)
    git = _git(obj.get("git", {}))
    writer_session_id = _identifier(obj.get("writer_session_id", ""), "writer_session_id", allow_empty=True)
    model_family = _enum(obj.get("model_family", "unknown"), VALID_MODEL_FAMILIES, "model_family")
    model_source = _enum(obj.get("model_source", "unknown"), VALID_MODEL_SOURCES, "model_source")
    model_verified = obj.get("model_verified", False)
    if not isinstance(model_verified, bool):
        raise SchemaError("model_verified must be boolean")
    origin = _text(obj.get("origin", "implementation-progress"), "origin", 80)
    intent = _text(obj.get("intent", "progress-maintenance"), "intent", 80)
    state_patch = _state_patch(obj.get("state_patch", {}))
    operation_payload_hash = _hash(obj.get("operation_payload_hash", ""), "operation_payload_hash", allow_empty=True)
    # The field is an optional integrity aid for operations created by this
    # implementation.  Older/manual material records remain valid without it;
    # the required chain fields are sequence, operation ID, previous hash, and
    # record hash.
    resulting_state_hash = _hash(obj.get("state_semantic_hash", ""), "state_semantic_hash", allow_empty=True)
    previous = _hash(obj.get("previous_event_hash", ""), "previous_event_hash", allow_empty=True)
    record_hash = _hash(obj.get("record_hash", ""), "record_hash", allow_empty=allow_unhashed)
    if not allow_unhashed and not record_hash:
        raise SchemaError("event record_hash is required")
    normalized = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "sequence": sequence,
        "event_id": event_id,
        "operation_id": operation_id,
        "timestamp": timestamp,
        "kind": kind,
        "summary": summary,
        "reason": reason,
        "next_action": next_action,
        "status": status,
        "classification": classification,
        "phase": phase,
        "plan_id": plan_id,
        "plan_path": plan_path,
        "references": references,
        "evidence_codes": evidence_codes,
        "git": git,
        "writer_session_id": writer_session_id,
        "model_family": model_family,
        "model_source": model_source,
        "model_verified": model_verified,
        "origin": origin,
        "intent": intent,
        "state_patch": state_patch,
        "operation_payload_hash": operation_payload_hash,
        "state_semantic_hash": resulting_state_hash,
        "previous_event_hash": previous,
        "record_hash": record_hash,
    }
    _reject_red(normalized, "event")
    if record_hash and record_hash != event_record_hash(normalized):
        raise SchemaError("event record_hash does not match the record")
    size = encoded_size(normalized)
    limit = hard_limit or (UNPLANNED_EVENT_HARD_LIMIT_BYTES if unplanned else EVENT_HARD_LIMIT_BYTES)
    if size > limit:
        raise SchemaError(f"event exceeds hard limit of {limit} UTF-8 bytes")
    return normalized


def event_record_hash(event: Mapping[str, Any]) -> str:
    material = dict(event)
    material.pop("record_hash", None)
    return digest(material)


def validate_manifest(manifest: Mapping[str, Any], *, hard_limit: int = MANIFEST_HARD_LIMIT_BYTES) -> dict[str, Any]:
    obj = _object(manifest, "manifest")
    _schema_version(obj, "manifest")
    _unknown_keys(obj, {"schema_version", "canonical_repo_identity", "generation", "plans"}, "manifest")
    identity = _identifier(obj.get("canonical_repo_identity", ""), "canonical_repo_identity", allow_empty=True)
    generation = _integer(obj.get("generation", 0), "generation", minimum=0)
    plans_raw = obj.get("plans", [])
    if not isinstance(plans_raw, list) or len(plans_raw) > 64:
        raise SchemaError("manifest plans must be a bounded list")
    plans: list[dict[str, Any]] = []
    seen_plan_ids: set[str] = set()
    for index, item in enumerate(plans_raw):
        pointer = _object(item, f"manifest.plans[{index}]")
        _unknown_keys(
            pointer,
            {"plan_id", "plan_path", "state_path", "status", "branch", "workspace_instance_id", "semantic_hash", "last_event_sequence"},
            f"manifest.plans[{index}]",
        )
        pointer_out = {
            "plan_id": _plan_id(pointer.get("plan_id")),
            "plan_path": _repo_relative_path(pointer.get("plan_path", ""), "manifest.plan_path", allow_empty=True),
            "state_path": _store_relative_path(pointer.get("state_path", ""), "manifest.state_path"),
            "status": _enum(pointer.get("status", "planned"), VALID_STATUSES, "manifest.status"),
            "branch": _text(pointer.get("branch", ""), "manifest.branch", 240, allow_empty=True),
            "workspace_instance_id": _identifier(pointer.get("workspace_instance_id", ""), "manifest.workspace_instance_id", allow_empty=True),
            "semantic_hash": _hash(pointer.get("semantic_hash", ""), "manifest.semantic_hash", allow_empty=True),
            "last_event_sequence": _integer(pointer.get("last_event_sequence", 0), "manifest.last_event_sequence", minimum=0),
        }
        if pointer_out["plan_id"] in seen_plan_ids:
            raise SchemaError("manifest contains duplicate plan pointers")
        seen_plan_ids.add(pointer_out["plan_id"])
        plans.append(pointer_out)
    normalized = {"schema_version": CURRENT_SCHEMA_VERSION, "canonical_repo_identity": identity, "generation": generation, "plans": plans}
    _reject_red(normalized, "manifest")
    if encoded_size(normalized) > hard_limit:
        raise SchemaError(f"manifest exceeds hard limit of {hard_limit} UTF-8 bytes")
    return normalized


def new_state(plan_id: str, *, plan_path: str = "", now: str = "", **fields: Any) -> dict[str, Any]:
    base = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "plan_id": plan_id,
        "plan_path": plan_path,
        "generation": 0,
        "status": "planned",
        "classification": "GREEN",
        "phase": "",
        "objective": "",
        "latest_decision": None,
        "next_action": "",
        "open_blockers": [],
        "open_questions": [],
        "validation": {},
        "active_files": [],
        "last_operation_id": "",
        "last_event_sequence": 0,
        "last_event_hash": "",
        "git": {},
        "writer_session_id": "",
        "model_family": "unknown",
        "model_source": "unknown",
        "model_verified": False,
        "origin": "implementation-progress",
        "intent": "progress-maintenance",
        "created_at": now,
        "updated_at": now,
    }
    base.update(fields)
    return validate_state(base, expected_plan_id=plan_id)


def _schema_version(obj: Mapping[str, Any], label: str) -> None:
    version = obj.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise SchemaError(f"{label}.schema_version must be an integer")
    if version > CURRENT_SCHEMA_VERSION:
        raise FutureSchemaError(f"{label} uses unsupported future schema {version}")
    if version != CURRENT_SCHEMA_VERSION:
        raise SchemaError(f"{label} schema_version {version} is unsupported")


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SchemaError(f"{label} must be a JSON object")
    return dict(value)


def _unknown_keys(obj: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(obj) - allowed
    if unknown:
        raise SchemaError(f"{label} contains unknown fields: {', '.join(sorted(unknown))}")


def _enum(value: Any, allowed: frozenset[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise SchemaError(f"{label} has an unsupported value")
    return value


def _integer(value: Any, label: str, *, minimum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise SchemaError(f"{label} must be an integer >= {minimum}")
    return value


def _text(value: Any, label: str, limit: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()) or len(value) > limit:
        raise SchemaError(f"{label} must be a bounded string")
    if "\x00" in value or any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise SchemaError(f"{label} contains a control character")
    if is_red(value):
        raise RedContentError(f"{label} contains RED-sensitive content")
    return value


def _timestamp(value: Any, label: str, *, allow_empty: bool = False) -> str:
    return _text(value, label, 64, allow_empty=allow_empty)


def _identifier(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise SchemaError(f"{label} must be a bounded identifier")
    if is_red(value):
        raise RedContentError(f"{label} contains RED-sensitive content")
    return value


def _plan_id(value: Any, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    if not isinstance(value, str) or not value or len(value) > 180 or "\\" in value or value.startswith("/"):
        raise SchemaError("plan_id must be a bounded relative identifier")
    parts = value.split("/")
    if len(parts) > 8 or any(not part or part in {".", ".."} for part in parts):
        raise SchemaError("plan_id contains traversal")
    if any(part.startswith("~") or any(ord(char) < 32 for char in part) for part in parts):
        raise SchemaError("plan_id contains an invalid component")
    if is_red(value):
        raise RedContentError("plan_id contains RED-sensitive content")
    return value


def _hash(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        raise SchemaError(f"{label} must be a sha256 digest")
    return value


def _text_list(value: Any, label: str, *, max_items: int, max_length: int) -> list[str]:
    if not isinstance(value, list) or len(value) > max_items:
        raise SchemaError(f"{label} must be a bounded list")
    return [_text(item, f"{label}[{index}]", max_length) for index, item in enumerate(value)]


def _code_list(value: Any, label: str, *, max_items: int) -> list[str]:
    if not isinstance(value, list) or len(value) > max_items:
        raise SchemaError(f"{label} must be a bounded list")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not _CODE_RE.fullmatch(item):
            raise SchemaError(f"{label}[{index}] must be a bounded evidence code")
        result.append(item)
    return result


def _path_list(value: Any, label: str, *, max_items: int, max_length: int) -> list[str]:
    if not isinstance(value, list) or len(value) > max_items:
        raise SchemaError(f"{label} must be a bounded list")
    return [_repo_relative_path(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _repo_relative_path(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    if not isinstance(value, str) or not value or len(value) > 320 or value.startswith("/") or "\\" in value:
        raise SchemaError(f"{label} must be a repository-relative path")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise SchemaError(f"{label} contains traversal or empty components")
    if is_red(value):
        raise RedContentError(f"{label} contains RED-sensitive content")
    return value


def _store_relative_path(value: Any, label: str) -> str:
    path = _repo_relative_path(value, label)
    if not path.startswith(".local-notes/ralph/implementation/") or not path.endswith("/state.json"):
        raise SchemaError(f"{label} must point inside the canonical implementation store")
    return path


def _validation(value: Any) -> dict[str, str]:
    obj = _object(value, "validation")
    if len(obj) > 16:
        raise SchemaError("validation has too many keys")
    result: dict[str, str] = {}
    for key, status in obj.items():
        if not isinstance(key, str) or not _CODE_RE.fullmatch(key):
            raise SchemaError("validation keys must be bounded evidence codes")
        result[key] = _enum(status, VALID_VALIDATION, f"validation.{key}")
    return result


def _state_patch(value: Any) -> dict[str, Any]:
    obj = _object(value, "state_patch")
    if len(obj) > len(STATE_PATCH_KEYS):
        raise SchemaError("state_patch contains too many fields")
    _unknown_keys(obj, set(STATE_PATCH_KEYS), "state_patch")
    result: dict[str, Any] = {}
    if "plan_path" in obj:
        result["plan_path"] = _repo_relative_path(obj["plan_path"], "state_patch.plan_path", allow_empty=True)
    if "status" in obj:
        result["status"] = _enum(obj["status"], VALID_STATUSES, "state_patch.status")
    if "classification" in obj:
        result["classification"] = _enum(obj["classification"], VALID_CLASSIFICATIONS, "state_patch.classification")
    if "phase" in obj:
        result["phase"] = _text(obj["phase"], "state_patch.phase", 160, allow_empty=True)
    if "objective" in obj:
        result["objective"] = _text(obj["objective"], "state_patch.objective", 480, allow_empty=True)
    if "latest_decision" in obj:
        decision = obj["latest_decision"]
        if decision is None:
            result["latest_decision"] = None
        else:
            decision_obj = _object(decision, "state_patch.latest_decision")
            _unknown_keys(decision_obj, {"event_id", "summary"}, "state_patch.latest_decision")
            result["latest_decision"] = {
                "event_id": _identifier(decision_obj.get("event_id", ""), "state_patch.latest_decision.event_id", allow_empty=True),
                "summary": _text(decision_obj.get("summary", ""), "state_patch.latest_decision.summary", 400, allow_empty=True),
            }
    if "next_action" in obj:
        result["next_action"] = _text(obj["next_action"], "state_patch.next_action", 400, allow_empty=True)
    if "open_blockers" in obj:
        result["open_blockers"] = _text_list(obj["open_blockers"], "state_patch.open_blockers", max_items=8, max_length=400)
    if "open_questions" in obj:
        result["open_questions"] = _text_list(obj["open_questions"], "state_patch.open_questions", max_items=8, max_length=400)
    if "validation" in obj:
        result["validation"] = _validation(obj["validation"])
    if "active_files" in obj:
        result["active_files"] = _path_list(obj["active_files"], "state_patch.active_files", max_items=16, max_length=320)
    if "git" in obj:
        result["git"] = _git(obj["git"])
    if "model_family" in obj:
        result["model_family"] = _enum(obj["model_family"], VALID_MODEL_FAMILIES, "state_patch.model_family")
    if "model_source" in obj:
        result["model_source"] = _enum(obj["model_source"], VALID_MODEL_SOURCES, "state_patch.model_source")
    if "model_verified" in obj:
        if not isinstance(obj["model_verified"], bool):
            raise SchemaError("state_patch.model_verified must be boolean")
        result["model_verified"] = obj["model_verified"]
    if "origin" in obj:
        result["origin"] = _text(obj["origin"], "state_patch.origin", 80)
    if "intent" in obj:
        result["intent"] = _text(obj["intent"], "state_patch.intent", 80)
    _reject_red(result, "state_patch")
    return result


def _git(value: Any) -> dict[str, str]:
    obj = _object(value, "git")
    _unknown_keys(obj, {"branch", "commit", "workspace_instance_id", "repository_id"}, "git")
    commit = _text(obj.get("commit", ""), "git.commit", 80, allow_empty=True)
    if commit and not _COMMIT_RE.fullmatch(commit):
        raise SchemaError("git.commit must be a hexadecimal Git commit")
    return {
        "branch": _text(obj.get("branch", ""), "git.branch", 240, allow_empty=True),
        "commit": commit,
        "workspace_instance_id": _identifier(obj.get("workspace_instance_id", ""), "git.workspace_instance_id", allow_empty=True),
        "repository_id": _identifier(obj.get("repository_id", ""), "git.repository_id", allow_empty=True),
    }


def _reject_red(value: Any, label: str) -> None:
    if is_red(canonical_json(value)):
        raise RedContentError(f"{label} contains RED-sensitive content")
