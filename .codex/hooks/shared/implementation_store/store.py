"""High-level operations for the canonical implementation-progress store.

The class is intentionally not imported by any lifecycle hook in this phase.
It is a small trusted boundary that later hook work can compose without
reintroducing legacy HTML/index writes.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .io import (
    CorruptRecordError,
    WriteMetadata,
    append_jsonl,
    locked_file,
    publish_json,
    quarantine_file,
    read_json,
    read_jsonl,
)
from .paths import PlanPaths, StorePaths, ensure_directory_chain, ensure_store_layout
from .schema import (
    EVENT_HARD_LIMIT_BYTES,
    MATERIAL_EVENT_KINDS,
    MANIFEST_HARD_LIMIT_BYTES,
    SchemaError,
    UNPLANNED_EVENT_HARD_LIMIT_BYTES,
    CURRENT_SCHEMA_VERSION,
    event_record_hash,
    new_state,
    state_semantic_hash,
    validate_event,
    validate_manifest,
    validate_state,
)
from .schema import canonical_json


class StoreError(RuntimeError):
    """Base error for an unsafe or logically invalid store operation."""


class IdempotencyError(StoreError):
    """An operation ID was reused with a different material payload."""


class IntegrityError(StoreError):
    """A journal sequence or hash chain cannot be trusted."""


@dataclass(frozen=True)
class StoreResult:
    changed: bool
    operation_id: str
    event_id: str = ""
    metadata: WriteMetadata = WriteMetadata()
    state: dict[str, Any] | None = None
    manifest: dict[str, Any] | None = None
    reason: str = ""

    @property
    def bytes_written(self) -> int:
        return self.metadata.bytes_written

    @property
    def files_written(self) -> tuple[str, ...]:
        return self.metadata.files_written


class ImplementationStore:
    """Secure access to one primary-checkout implementation store."""

    def __init__(self, paths: StorePaths):
        self.paths = paths

    def plan_paths(self, plan_id: str) -> PlanPaths:
        return self.paths.for_plan(plan_id)

    # ----- side-effect-free reads -------------------------------------------------

    def read_manifest(self) -> dict[str, Any] | None:
        return read_json(self.paths.manifest, validate_manifest, label="manifest")

    def read_state(self, plan_id: str) -> dict[str, Any] | None:
        plan = self.plan_paths(plan_id)
        return read_json(plan.state, lambda value: validate_state(value, expected_plan_id=plan.plan_id), label="state")

    def read_events(self, plan_id: str) -> tuple[dict[str, Any], ...]:
        plan = self.plan_paths(plan_id)
        result = self._read_plan_events(plan)
        return result.records

    def read_unplanned_events(self) -> tuple[dict[str, Any], ...]:
        result = read_jsonl(
            self.paths.unplanned_events,
            lambda value: validate_event(value, unplanned=True),
            label="unplanned-events.jsonl",
            unplanned=True,
        )
        self._validate_sequence_and_hashes(result.records, plan_id=None)
        return result.records

    # ----- plan lifecycle ----------------------------------------------------------

    def register_plan(
        self,
        plan_id: str,
        *,
        plan_path: str = "",
        operation_id: str | None = None,
        now: str | None = None,
        provenance: Mapping[str, Any] | None = None,
        objective: str = "",
        phase: str = "",
        next_action: str = "",
        status: str = "planned",
    ) -> StoreResult:
        plan = self.plan_paths(plan_id)
        operation = _operation_id(operation_id)
        timestamp = now or _now()
        # Build and validate the complete bounded snapshot before creating a
        # directory, lock, or journal file.  Over-limit and RED input must be
        # rejected before any store mutation.
        initial_state = new_state(
            plan.plan_id,
            plan_path=plan_path,
            now=timestamp,
            status=status,
            objective=objective,
            phase=phase,
            next_action=next_action,
            **_provenance_fields(provenance),
        )
        ensure_store_layout(self.paths)
        ensure_directory_chain(plan.root, mode=0o700)
        with locked_file(plan.state_lock):
            current = self._load_state_for_write(plan)
            if current is not None:
                existing = self._operation_event(plan, operation)
                if existing is not None:
                    self._assert_same_operation(existing, kind="started", summary="Plan registered", operation=operation)
                    for field in ("plan_path", "status", "phase", "objective", "next_action", "git", "model_family", "model_source", "model_verified"):
                        if current.get(field) != initial_state.get(field):
                            raise IdempotencyError(f"operation_id {operation} was reused with a different payload")
                    return StoreResult(False, operation, existing["event_id"], reason="idempotent retry", state=current)
                # Registration is a discovery transition; an existing plan is
                # not silently reset or overwritten.
                raise StoreError("plan is already registered")
            if plan.events.exists():
                # A journal without a readable snapshot is crash/recovery
                # evidence, not permission to start a second sequence at one.
                raise StoreError("plan has journal evidence but no usable state; replay is required")
            state = initial_state
            event = self._build_event(
                plan,
                state,
                operation_id=operation,
                kind="started",
                summary="Plan registered",
                timestamp=timestamp,
                sequence=1,
                previous_event_hash="",
                provenance=provenance,
            )
            metadata = append_jsonl(plan.events, event, hard_limit=EVENT_HARD_LIMIT_BYTES)
            state = self._state_after_event(state, event, timestamp=timestamp)
            metadata = metadata.plus(publish_json(plan.state, state, hard_limit=8 * 1024))
        manifest, manifest_meta = self._publish_manifest_pointer(state, force=True)
        metadata = metadata.plus(manifest_meta)
        return StoreResult(True, operation, event["event_id"], metadata, state, manifest)

    def record_event(
        self,
        plan_id: str,
        *,
        kind: str,
        operation_id: str | None = None,
        summary: str = "",
        reason: str = "",
        next_action: str = "",
        references: list[str] | None = None,
        evidence_codes: list[str] | None = None,
        state_update: Mapping[str, Any] | None = None,
        now: str | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> StoreResult:
        plan = self.plan_paths(plan_id)
        if kind not in MATERIAL_EVENT_KINDS or kind == "loose_commit_recorded":
            raise SchemaError("unknown or out-of-scope material event kind")
        operation = _operation_id(operation_id)
        timestamp = now or _now()
        # Validate bounded caller input before creating a lock or directory.
        # The locked read below repeats the computation against the current
        # state to close the normal concurrent-writer race.
        try:
            preview_state = self.read_state(plan_id)
        except CorruptRecordError:
            # A write/recovery boundary may preserve malformed current bytes
            # in a quarantine sibling.  Future schemas are intentionally not
            # caught here and remain hard-blocked.
            ensure_store_layout(self.paths)
            ensure_directory_chain(plan.root, mode=0o700)
            with locked_file(plan.state_lock):
                self._load_state_for_write(plan)
            raise StoreError("plan is not registered")
        if preview_state is None:
            raise StoreError("plan is not registered")
        preview_candidate = self._apply_update(preview_state, state_update or {}, kind=kind, summary=summary, next_action=next_action)
        if provenance is not None:
            preview_candidate.update(_provenance_fields(provenance))
        validate_state(preview_candidate, expected_plan_id=plan.plan_id)
        ensure_store_layout(self.paths)
        ensure_directory_chain(plan.root, mode=0o700)
        with locked_file(plan.state_lock):
            state = self._load_state_for_write(plan)
            if state is None:
                raise StoreError("plan is not registered")
            events = self._read_plan_events(plan).records
            candidate = self._apply_update(state, state_update or {}, kind=kind, summary=summary, next_action=next_action)
            if provenance is not None:
                candidate.update(_provenance_fields(provenance))
            candidate = validate_state(candidate, expected_plan_id=plan.plan_id)
            existing = self._operation_event_from_records(events, operation)
            if existing is not None:
                candidate_event = self._build_event(
                    plan,
                    candidate,
                    operation_id=operation,
                    kind=kind,
                    summary=summary,
                    reason=reason,
                    next_action=next_action,
                    references=references,
                    evidence_codes=evidence_codes,
                    timestamp=timestamp,
                    sequence=existing["sequence"],
                    previous_event_hash=existing["previous_event_hash"],
                    provenance=provenance,
                )
                self._assert_same_operation(existing, candidate_event=candidate_event, operation=operation)
                return StoreResult(False, operation, existing["event_id"], reason="idempotent retry", state=state)
            if state_semantic_hash(candidate) == state_semantic_hash(state):
                return StoreResult(False, operation, reason="semantic state unchanged", state=state)
            sequence = len(events) + 1
            previous = events[-1]["record_hash"] if events else ""
            event = self._build_event(
                plan,
                candidate,
                operation_id=operation,
                kind=kind,
                summary=summary,
                reason=reason,
                next_action=next_action,
                references=references,
                evidence_codes=evidence_codes,
                timestamp=timestamp,
                sequence=sequence,
                previous_event_hash=previous,
                provenance=provenance,
            )
            metadata = append_jsonl(plan.events, event, hard_limit=EVENT_HARD_LIMIT_BYTES)
            candidate = self._state_after_event(candidate, event, timestamp=timestamp)
            metadata = metadata.plus(publish_json(plan.state, candidate, hard_limit=8 * 1024))
            status_changed = candidate.get("status") != state.get("status")
        manifest = self.read_manifest()
        manifest_meta = WriteMetadata()
        if status_changed:
            manifest, manifest_meta = self._publish_manifest_pointer(candidate, force=False)
            metadata = metadata.plus(manifest_meta)
        return StoreResult(True, operation, event["event_id"], metadata, candidate, manifest)

    def update_state(
        self,
        plan_id: str,
        updates: Mapping[str, Any],
        *,
        operation_id: str | None = None,
        kind: str = "validation_changed",
        summary: str = "",
        now: str | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> StoreResult:
        return self.record_event(
            plan_id,
            kind=kind,
            operation_id=operation_id,
            summary=summary,
            state_update=updates,
            now=now,
            provenance=provenance,
        )

    # ----- loose commits -----------------------------------------------------------

    def append_unplanned_commit(
        self,
        *,
        operation_id: str,
        summary: str,
        references: list[str] | None = None,
        evidence_codes: list[str] | None = None,
        now: str | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> StoreResult:
        operation = _operation_id(operation_id)
        timestamp = now or _now()
        # Validate the complete bounded line before creating the store or its
        # lock.  The sequence and predecessor are rebuilt under the lock.
        self._build_unplanned_event(
            operation,
            summary,
            references or [],
            evidence_codes or [],
            timestamp,
            sequence=1,
            previous_event_hash="",
            provenance=provenance,
        )
        ensure_store_layout(self.paths)
        with locked_file(self.paths.manifest_lock):
            events = read_jsonl(
                self.paths.unplanned_events,
                lambda value: validate_event(value, unplanned=True),
                label="unplanned-events.jsonl",
                unplanned=True,
            ).records
            existing = self._operation_event_from_records(events, operation)
            if existing is not None:
                candidate = self._build_unplanned_event(
                    operation,
                    summary,
                    references or [],
                    evidence_codes or [],
                    timestamp,
                    sequence=existing["sequence"],
                    previous_event_hash=existing["previous_event_hash"],
                    provenance=provenance,
                )
                self._assert_same_operation(existing, candidate_event=candidate, operation=operation)
                return StoreResult(False, operation, existing["event_id"], reason="idempotent retry")
            previous = events[-1]["record_hash"] if events else ""
            event = self._build_unplanned_event(
                operation,
                summary,
                references or [],
                evidence_codes or [],
                timestamp,
                sequence=len(events) + 1,
                previous_event_hash=previous,
                provenance=provenance,
            )
            metadata = append_jsonl(self.paths.unplanned_events, event, hard_limit=UNPLANNED_EVENT_HARD_LIMIT_BYTES)
        return StoreResult(True, operation, event["event_id"], metadata)

    # ----- replay/recovery ---------------------------------------------------------

    def replay_plan(self, plan_id: str, *, now: str | None = None) -> StoreResult:
        plan = self.plan_paths(plan_id)
        ensure_store_layout(self.paths)
        ensure_directory_chain(plan.root, mode=0o700)
        timestamp = now or _now()
        with locked_file(plan.state_lock):
            state = self._load_state_for_write(plan)
            events = self._read_plan_events(plan).records
            self._validate_sequence_and_hashes(events, plan_id=plan.plan_id)
            if state is None:
                if not events:
                    return StoreResult(False, "", reason="no state to replay")
                first = events[0]
                state = new_state(
                    plan.plan_id,
                    plan_path=first.get("plan_path", ""),
                    now=timestamp,
                    status=first.get("status", "planned"),
                    phase=first.get("phase", ""),
                    git=first.get("git", {}),
                    writer_session_id=first.get("writer_session_id", ""),
                    model_family=first.get("model_family", "unknown"),
                    model_source=first.get("model_source", "unknown"),
                    model_verified=first.get("model_verified", False),
                    origin=first.get("origin", "implementation-progress"),
                    intent=first.get("intent", "progress-maintenance"),
                )
            if state["last_event_sequence"] > len(events):
                raise IntegrityError("state points beyond the end of its journal")
            if state["last_event_sequence"] > 0 and state["last_event_hash"] != events[state["last_event_sequence"] - 1]["record_hash"]:
                raise IntegrityError("state last_event_hash does not match its journal")
            if state["last_event_sequence"] == len(events):
                return StoreResult(False, "", state=state, reason="already current")
            recovered = dict(state)
            for event in events[state["last_event_sequence"] :]:
                recovered = self._state_after_event(recovered, event, timestamp=timestamp)
            recovered = validate_state(recovered, expected_plan_id=plan.plan_id)
            metadata = publish_json(plan.state, recovered, hard_limit=8 * 1024)
        return StoreResult(True, recovered.get("last_operation_id", ""), metadata=metadata, state=recovered, reason="replayed journal")

    # ----- internal helpers --------------------------------------------------------

    def _read_plan_events(self, plan: PlanPaths):
        result = read_jsonl(
            plan.events,
            lambda value: validate_event(value, expected_plan_id=plan.plan_id),
            label=f"events for {plan.plan_id}",
        )
        self._validate_sequence_and_hashes(result.records, plan_id=plan.plan_id)
        return result

    def _load_state_for_write(self, plan: PlanPaths) -> dict[str, Any] | None:
        try:
            return read_json(plan.state, lambda value: validate_state(value, expected_plan_id=plan.plan_id), label=f"state for {plan.plan_id}")
        except CorruptRecordError:
            # Mutation is the explicit recovery boundary.  The original bytes
            # are moved to a deterministic sibling before a caller can publish.
            if plan.state.exists():
                quarantine_file(plan.state, reason="malformed current schema")
            return None

    def _publish_manifest_pointer(self, state: Mapping[str, Any], *, force: bool) -> tuple[dict[str, Any], WriteMetadata]:
        ensure_store_layout(self.paths)
        with locked_file(self.paths.manifest_lock):
            current = None
            try:
                current = read_json(self.paths.manifest, validate_manifest, label="manifest")
            except CorruptRecordError:
                if self.paths.manifest.exists():
                    quarantine_file(self.paths.manifest, reason="malformed current schema")
            if current is None:
                current = {
                    "schema_version": CURRENT_SCHEMA_VERSION,
                    "canonical_repo_identity": _repo_identity(self.paths.primary_root),
                    "generation": 0,
                    "plans": [],
                }
            pointer = {
                "plan_id": state["plan_id"],
                "plan_path": state.get("plan_path", ""),
                "state_path": str((self.paths.root / "plans" / state["plan_id"] / "state.json").relative_to(self.paths.primary_root)),
                "status": state["status"],
                "branch": state.get("git", {}).get("branch", ""),
                "workspace_instance_id": state.get("git", {}).get("workspace_instance_id", ""),
                "semantic_hash": state.get("semantic_hash", ""),
                "last_event_sequence": state.get("last_event_sequence", 0),
            }
            plans = list(current.get("plans", []))
            found = next((index for index, item in enumerate(plans) if item.get("plan_id") == pointer["plan_id"]), None)
            if found is None:
                plans.append(pointer)
                changed = True
            else:
                existing = plans[found]
                # The manifest intentionally tracks discovery/status pointers,
                # not every phase, validation, or event transition.
                if existing.get("status") != pointer["status"] or force and existing != pointer:
                    plans[found] = pointer
                    changed = True
                else:
                    changed = False
            candidate = validate_manifest(
                {
                    **current,
                    "generation": current.get("generation", 0) + (1 if changed else 0),
                    "plans": plans,
                }
            )
            if not changed:
                return candidate, WriteMetadata()
            metadata = publish_json(self.paths.manifest, candidate, hard_limit=MANIFEST_HARD_LIMIT_BYTES)
            return candidate, metadata

    def _build_event(
        self,
        plan: PlanPaths,
        state: Mapping[str, Any],
        *,
        operation_id: str,
        kind: str,
        summary: str = "",
        reason: str = "",
        next_action: str = "",
        references: list[str] | None = None,
        evidence_codes: list[str] | None = None,
        timestamp: str,
        sequence: int,
        previous_event_hash: str,
        provenance: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        material = {
            "plan_id": plan.plan_id,
            "kind": kind,
            "operation_id": operation_id,
            "sequence": sequence,
            "summary": summary,
            "reason": reason,
            "next_action": next_action,
            "references": references or [],
            "evidence_codes": evidence_codes or [],
        }
        event_id = "evt-" + hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()[:32]
        event = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "sequence": sequence,
            "event_id": event_id,
            "operation_id": operation_id,
            "timestamp": timestamp,
            "kind": kind,
            "summary": summary,
            "reason": reason,
            "next_action": next_action,
            "status": state.get("status", "planned"),
            "classification": state.get("classification", "GREEN"),
            "phase": state.get("phase", ""),
            "plan_id": plan.plan_id,
            "plan_path": state.get("plan_path", ""),
            "references": references or [],
            "evidence_codes": evidence_codes or [],
            "git": state.get("git", {}),
            "writer_session_id": state.get("writer_session_id", ""),
            "model_family": state.get("model_family", "unknown"),
            "model_source": state.get("model_source", "unknown"),
            "model_verified": state.get("model_verified", False),
            "origin": state.get("origin", "implementation-progress"),
            "intent": state.get("intent", "progress-maintenance"),
            "state_semantic_hash": _operation_state_hash(state),
            "previous_event_hash": previous_event_hash,
            "record_hash": "",
        }
        event["record_hash"] = event_record_hash(validate_event(event, expected_plan_id=plan.plan_id, allow_unhashed=True))
        return validate_event(event, expected_plan_id=plan.plan_id)

    def _build_unplanned_event(
        self,
        operation: str,
        summary: str,
        references: list[str],
        evidence_codes: list[str],
        timestamp: str,
        *,
        sequence: int,
        previous_event_hash: str,
        provenance: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        fields = _provenance_fields(provenance)
        event = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "sequence": sequence,
            "event_id": "evt-" + hashlib.sha256(f"loose:{operation}:{sequence}".encode()).hexdigest()[:32],
            "operation_id": operation,
            "timestamp": timestamp,
            "kind": "loose_commit_recorded",
            "summary": summary,
            "reason": "",
            "next_action": "",
            "status": "planned",
            "classification": "GREEN",
            "phase": "",
            "plan_id": "",
            "plan_path": "",
            "references": references,
            "evidence_codes": evidence_codes,
            "git": fields.get("git", {}),
            "writer_session_id": fields.get("writer_session_id", ""),
            "model_family": fields.get("model_family", "unknown"),
            "model_source": fields.get("model_source", "unknown"),
            "model_verified": fields.get("model_verified", False),
            "origin": "implementation-progress",
            "intent": "progress-maintenance",
            "state_semantic_hash": "",
            "previous_event_hash": previous_event_hash,
            "record_hash": "",
        }
        event["record_hash"] = event_record_hash(validate_event(event, unplanned=True, allow_unhashed=True))
        return validate_event(event, unplanned=True)

    @staticmethod
    def _state_after_event(state: Mapping[str, Any], event: Mapping[str, Any], *, timestamp: str) -> dict[str, Any]:
        result = dict(state)
        result.update(
            {
                "generation": int(state.get("generation", 0)) + 1,
                "last_operation_id": event["operation_id"],
                "last_event_sequence": event["sequence"],
                "last_event_hash": event["record_hash"],
                "updated_at": timestamp,
            }
        )
        for field in ("status", "classification", "phase", "next_action"):
            if field in event:
                result[field] = event[field]
        if event.get("plan_path"):
            result["plan_path"] = event["plan_path"]
        if event.get("git"):
            result["git"] = event["git"]
        for field in ("writer_session_id", "model_family", "model_source", "model_verified", "origin", "intent"):
            if field in event:
                result[field] = event[field]
        if event.get("kind") == "decision":
            result["latest_decision"] = {"event_id": event["event_id"], "summary": event.get("summary", "")}
        return result

    @staticmethod
    def _apply_update(state: Mapping[str, Any], updates: Mapping[str, Any], *, kind: str, summary: str, next_action: str) -> dict[str, Any]:
        result = dict(state)
        for key, value in updates.items():
            if key in {"schema_version", "plan_id", "semantic_hash", "generation", "last_operation_id", "last_event_sequence", "last_event_hash", "created_at", "updated_at"}:
                raise SchemaError(f"{key} is derived and cannot be directly updated")
            result[key] = value
        if next_action:
            result["next_action"] = next_action
        if kind == "decision" and summary:
            # The event ID is filled in after the event is built.  A stable
            # placeholder makes the decision summary part of the candidate
            # semantic state so a real decision cannot be mistaken for a
            # no-op before its journal record exists.
            result["latest_decision"] = {"event_id": "pending", "summary": summary}
        if kind == "completed":
            result["status"] = "completed"
        elif kind == "reopened":
            result["status"] = "reopened"
        elif kind == "blocker_opened":
            result["status"] = "blocked"
        elif kind == "blocker_resolved" and result.get("status") == "blocked":
            result["status"] = "active"
        return result

    @staticmethod
    def _operation_event(plan: PlanPaths, operation: str) -> dict[str, Any] | None:
        result = read_jsonl(
            plan.events,
            lambda value: validate_event(value, expected_plan_id=plan.plan_id),
            label=f"events for {plan.plan_id}",
        )
        return ImplementationStore._operation_event_from_records(result.records, operation)

    @staticmethod
    def _operation_event_from_records(events: tuple[dict[str, Any], ...] | list[dict[str, Any]], operation: str) -> dict[str, Any] | None:
        return next((event for event in events if event.get("operation_id") == operation), None)

    @staticmethod
    def _assert_same_operation(
        existing: Mapping[str, Any],
        *,
        operation: str,
        kind: str | None = None,
        summary: str | None = None,
        candidate_event: Mapping[str, Any] | None = None,
    ) -> None:
        if candidate_event is not None:
            left = {key: value for key, value in existing.items() if key not in {"event_id", "timestamp", "record_hash"}}
            right = {key: value for key, value in candidate_event.items() if key not in {"event_id", "timestamp", "record_hash"}}
            if left != right:
                raise IdempotencyError(f"operation_id {operation} was reused with a different payload")
            return
        if kind is not None and (existing.get("kind") != kind or existing.get("summary") != summary):
            raise IdempotencyError(f"operation_id {operation} was reused with a different payload")

    @staticmethod
    def _validate_sequence_and_hashes(events: tuple[dict[str, Any], ...], *, plan_id: str | None) -> None:
        previous = ""
        for expected, event in enumerate(events, start=1):
            if event["sequence"] != expected:
                raise IntegrityError(f"journal sequence gap at {expected}")
            if event.get("previous_event_hash", "") != previous:
                raise IntegrityError(f"journal previous hash mismatch at {expected}")
            if not event.get("record_hash") or event["record_hash"] != event_record_hash(event):
                raise IntegrityError(f"journal record hash mismatch at {expected}")
            previous = event["record_hash"]


def _operation_id(value: str | None) -> str:
    if value:
        return value
    return "op-" + uuid.uuid4().hex


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _repo_identity(primary_root: Path) -> str:
    return "repo-" + hashlib.sha256(str(primary_root).encode("utf-8")).hexdigest()[:24]


def _provenance_fields(provenance: Mapping[str, Any] | None) -> dict[str, Any]:
    source = dict(provenance or {})
    return {
        "git": dict(source.get("git") or {}),
        "writer_session_id": source.get("writer_session_id", ""),
        "model_family": source.get("model_family", "unknown"),
        "model_source": source.get("model_source", "unknown"),
        "model_verified": source.get("model_verified", False),
        "origin": source.get("origin", "implementation-progress"),
        "intent": source.get("intent", "progress-maintenance"),
    }


def _operation_state_hash(state: Mapping[str, Any]) -> str:
    """Hash the material result of an operation, excluding journal linkage."""

    projection = dict(state)
    for key in (
        "semantic_hash",
        "generation",
        "last_operation_id",
        "last_event_sequence",
        "last_event_hash",
        "updated_at",
        "created_at",
        "writer_session_id",
    ):
        projection.pop(key, None)
    return state_semantic_hash(projection)
