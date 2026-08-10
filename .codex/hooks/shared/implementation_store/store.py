"""High-level operations for the canonical implementation-progress store.

The lifecycle adapter imports this small trusted boundary directly. Hooks may
compose it only through bounded semantic operations; legacy HTML/index writes
remain outside the runtime path.
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
    publish_bytes,
    quarantine_file,
    read_json,
    read_jsonl,
)
from .paths import (
    PlanPaths,
    StorePathError,
    StorePaths,
    directory_stat,
    ensure_directory_chain,
    ensure_store_layout,
    _reject_symlink_components,
)
from .schema import (
    CONTEXT_LEDGER_HARD_LIMIT_BYTES,
    EVENT_HARD_LIMIT_BYTES,
    MATERIAL_EVENT_KINDS,
    MANIFEST_HARD_LIMIT_BYTES,
    SchemaError,
    STATE_PATCH_KEYS,
    UNPLANNED_EVENT_HARD_LIMIT_BYTES,
    CURRENT_SCHEMA_VERSION,
    digest,
    event_record_hash,
    new_state,
    state_semantic_hash,
    validate_event,
    validate_context_ledger_record,
    validate_manifest,
    validate_operation_id,
    validate_state,
    context_ledger_key,
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


@dataclass(frozen=True)
class ContextEmissionResult:
    """Result of a content-free context ledger claim."""

    emitted: bool
    metadata: WriteMetadata = WriteMetadata()
    reason: str = ""

    @property
    def changed(self) -> bool:
        return self.emitted


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
        state = read_json(plan.state, lambda value: validate_state(value, expected_plan_id=plan.plan_id), label="state")
        if state is None:
            return None
        events = self._read_plan_events(plan, reject_partial=False).records
        self._validate_ownership(state)
        self._validate_state_cursor(state, events)
        return state

    def read_state_identity(self, plan_id: str) -> dict[str, Any] | None:
        """Read only the validated state snapshot, without journal history.

        Hooks use this bounded lookup to put progress generation and writer
        identity into a cache claim.  Full event-chain verification remains a
        miss-only operation before a model-visible capsule is rendered.
        """

        plan = self.plan_paths(plan_id)
        state = read_json(plan.state, lambda value: validate_state(value, expected_plan_id=plan.plan_id), label="state")
        if state is not None:
            self._validate_ownership(state)
        return state

    def read_events(self, plan_id: str) -> tuple[dict[str, Any], ...]:
        plan = self.plan_paths(plan_id)
        result = self._read_plan_events(plan, reject_partial=False)
        return result.records

    def read_unplanned_events(self) -> tuple[dict[str, Any], ...]:
        result = read_jsonl(
            self.paths.unplanned_events,
            lambda value: validate_event(value, unplanned=True),
            label="unplanned-events.jsonl",
            unplanned=True,
        )
        self._validate_sequence_and_hashes(result.records, plan_id=None)
        self._validate_event_ownership(result.records)
        return result.records

    def read_context_ledger(self) -> tuple[dict[str, Any], ...]:
        """Read the emission ledger without creating or changing anything."""

        result = read_jsonl(
            self.paths.context_ledger,
            validate_context_ledger_record,
            label="context-emissions.jsonl",
        )
        if result.partial_final_line:
            raise IntegrityError("context emission ledger has an incomplete final line")
        seen: set[tuple[str, str, str, str, str, int, str]] = set()
        for record in result.records:
            key = context_ledger_key(record)
            if key in seen:
                raise IntegrityError("context emission ledger contains a duplicate key")
            seen.add(key)
        return result.records

    def claim_context_emission(self, record: Mapping[str, Any]) -> ContextEmissionResult:
        """Claim one ledger key, writing only when the caller will emit it.

        The caller must construct and validate a non-empty capsule before this
        method is called. A duplicate claim is read-only.
        """

        normalized = validate_context_ledger_record(record)
        key = context_ledger_key(normalized)
        # A hit must remain genuinely read-only.  Check an existing ledger
        # before creating a lock/layout entry; the locked recheck below closes
        # the writer race for misses.
        if self.paths.context_ledger.exists():
            for existing in self.read_context_ledger():
                if context_ledger_key(existing) == key:
                    return ContextEmissionResult(False, reason="ledger hit")
        ensure_store_layout(self.paths)
        with locked_file(self.paths.context_ledger_lock):
            result = read_jsonl(
                self.paths.context_ledger,
                validate_context_ledger_record,
                label="context-emissions.jsonl",
            )
            if result.partial_final_line:
                raise IntegrityError("context emission ledger has an incomplete final line")
            for existing in result.records:
                if context_ledger_key(existing) == key:
                    return ContextEmissionResult(False, reason="ledger hit")
            metadata = append_jsonl(
                self.paths.context_ledger,
                normalized,
                hard_limit=CONTEXT_LEDGER_HARD_LIMIT_BYTES,
            )
        return ContextEmissionResult(True, metadata=metadata, reason="emitted")

    def has_context_emission(self, record: Mapping[str, Any]) -> bool:
        """Return whether a ledger key exists without creating a layout/lock."""

        normalized = validate_context_ledger_record(record)
        key = context_ledger_key(normalized)
        if not self.paths.context_ledger.exists():
            return False
        return any(context_ledger_key(item) == key for item in self.read_context_ledger())

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
        summary: str = "Plan registered",
        reason: str = "",
        references: list[str] | None = None,
        evidence_codes: list[str] | None = None,
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
            **self._provenance_for_store(provenance),
        )
        ensure_store_layout(self.paths)
        ensure_directory_chain(plan.root, mode=0o700)
        with locked_file(plan.state_lock):
            current = self._load_state_for_write(plan)
            events_result = self._read_plan_events(plan, reject_partial=True)
            events = events_result.records
            recovery_needed = False
            if current is None and events:
                current = self._reconstruct_state(plan, events, timestamp=timestamp)
                recovery_needed = True
            elif current is not None:
                self._validate_ownership(current)
                current, recovery_needed = self._reconcile_state(current, events, timestamp=timestamp)
            if current is not None:
                existing = self._operation_event_from_records(events, operation)
                if existing is not None:
                    expected = self._build_event(
                        plan,
                        initial_state,
                        operation_id=operation,
                        kind="started",
                        summary=summary,
                        reason=reason,
                        next_action=next_action,
                        references=references,
                        evidence_codes=evidence_codes,
                        timestamp=timestamp,
                        sequence=existing["sequence"],
                        previous_event_hash=existing["previous_event_hash"],
                        state_patch=_material_state_patch({}, initial_state, include_all=True),
                        operation_payload=_registration_operation_payload(
                            initial_state,
                            summary=summary,
                            reason=reason,
                            references=references,
                            evidence_codes=evidence_codes,
                        ),
                    )
                    self._assert_same_operation(existing, candidate_event=expected, operation=operation)
                    metadata = publish_json(plan.state, current, hard_limit=8 * 1024) if recovery_needed else WriteMetadata()
                    manifest, manifest_meta = self._publish_manifest_pointer(current, force=False)
                    return StoreResult(False, operation, existing["event_id"], metadata=metadata.plus(manifest_meta), reason="idempotent retry", state=current, manifest=manifest)
                # Registration is a discovery transition; an existing plan is
                # not silently reset or overwritten.
                raise StoreError("plan is already registered")
            state = initial_state
            event = self._build_event(
                plan,
                state,
                operation_id=operation,
                kind="started",
                summary=summary,
                reason=reason,
                next_action=next_action,
                references=references,
                evidence_codes=evidence_codes,
                timestamp=timestamp,
                sequence=1,
                previous_event_hash="",
                state_patch=_material_state_patch({}, state, include_all=True),
                operation_payload=_registration_operation_payload(
                    state,
                    summary=summary,
                    reason=reason,
                    references=references,
                    evidence_codes=evidence_codes,
                ),
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
        provenance_fields = self._provenance_for_store(provenance) if provenance is not None else None
        # Validate bounded caller input before creating a lock or directory.
        # The locked read below repeats the computation against the current
        # state to close the normal concurrent-writer race.
        try:
            preview_state = self.read_state(plan_id)
        except CorruptRecordError:
            # Preserve the historical malformed-state recovery boundary, but
            # never mistake a malformed journal for an unregistered plan.
            # Future schemas are intentionally not caught here and remain
            # hard-blocked.
            try:
                read_json(plan.state, lambda value: validate_state(value, expected_plan_id=plan.plan_id), label=f"state for {plan.plan_id}")
            except CorruptRecordError:
                ensure_store_layout(self.paths)
                ensure_directory_chain(plan.root, mode=0o700)
                with locked_file(plan.state_lock):
                    self._load_state_for_write(plan)
                raise StoreError("plan is not registered")
            raise
        if preview_state is None:
            raise StoreError("plan is not registered")
        preview_candidate = self._apply_update(preview_state, state_update or {}, kind=kind, summary=summary, next_action=next_action)
        if provenance_fields is not None:
            preview_candidate.update(provenance_fields)
        validate_state(preview_candidate, expected_plan_id=plan.plan_id)
        self._validate_ownership(preview_candidate)
        ensure_store_layout(self.paths)
        ensure_directory_chain(plan.root, mode=0o700)
        with locked_file(plan.state_lock):
            state = self._load_state_for_write(plan)
            events_result = self._read_plan_events(plan, reject_partial=True)
            events = events_result.records
            recovery_needed = False
            if state is None:
                if not events:
                    raise StoreError("plan is not registered")
                state = self._reconstruct_state(plan, events, timestamp=timestamp)
                recovery_needed = True
            else:
                self._validate_ownership(state)
                state, recovery_needed = self._reconcile_state(state, events, timestamp=timestamp)
            candidate = self._apply_update(state, state_update or {}, kind=kind, summary=summary, next_action=next_action)
            if provenance_fields is not None:
                candidate.update(provenance_fields)
            candidate = validate_state(candidate, expected_plan_id=plan.plan_id)
            self._validate_ownership(candidate)
            existing = self._operation_event_from_records(events, operation)
            operation_payload = _record_operation_payload(
                kind=kind,
                summary=summary,
                reason=reason,
                next_action=next_action,
                references=references,
                evidence_codes=evidence_codes,
                state_update=state_update,
                provenance=provenance_fields,
            )
            candidate_patch = _material_state_patch(state, candidate)
            # Build a side-effect-free candidate event before the semantic
            # no-op check.  This validates summary/reason/references/evidence
            # sensitivity and event limits even when the state itself is
            # unchanged.
            self._build_event(
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
                sequence=1,
                previous_event_hash="",
                state_patch=candidate_patch,
                operation_payload=operation_payload,
                provenance=provenance,
            )
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
                    state_patch=candidate_patch,
                    operation_payload=operation_payload,
                    provenance=provenance,
                )
                self._assert_same_operation(existing, candidate_event=candidate_event, operation=operation)
                metadata = publish_json(plan.state, state, hard_limit=8 * 1024) if recovery_needed else WriteMetadata()
                return StoreResult(False, operation, existing["event_id"], metadata=metadata, reason="idempotent retry", state=state)
            if state_semantic_hash(candidate) == state_semantic_hash(state):
                metadata = publish_json(plan.state, state, hard_limit=8 * 1024) if recovery_needed else WriteMetadata()
                return StoreResult(False, operation, metadata=metadata, reason="semantic state unchanged", state=state)
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
                state_patch=candidate_patch,
                operation_payload=operation_payload,
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
            events_result = read_jsonl(
                self.paths.unplanned_events,
                lambda value: validate_event(value, unplanned=True),
                label="unplanned-events.jsonl",
                unplanned=True,
            )
            if events_result.partial_final_line:
                raise IntegrityError("unplanned journal has an incomplete final line; explicit repair is required")
            events = events_result.records
            self._validate_sequence_and_hashes(events, plan_id=None)
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
            events_result = self._read_plan_events(plan, reject_partial=False)
            events = events_result.records
            if state is None:
                if not events:
                    return StoreResult(False, "", reason="no state to replay")
                state = self._reconstruct_state(plan, events, timestamp=timestamp)
                metadata = publish_json(plan.state, state, hard_limit=8 * 1024)
                return StoreResult(True, state.get("last_operation_id", ""), metadata=metadata, state=state, reason="replayed journal")
            self._validate_ownership(state)
            state, recovery_needed = self._reconcile_state(state, events, timestamp=timestamp)
            if not recovery_needed:
                return StoreResult(False, "", state=state, reason="already current")
            metadata = publish_json(plan.state, state, hard_limit=8 * 1024)
        return StoreResult(True, state.get("last_operation_id", ""), metadata=metadata, state=state, reason="replayed journal")

    def publish_derived_view(self, output: Path | str, content: str, *, hard_limit: int = 256 * 1024) -> WriteMetadata:
        """Persist an explicitly requested derived view through the store I/O boundary.

        Canonical state and journal records remain the only business writes.  This
        helper is reserved for explicit export/rebuild commands and refuses paths
        outside the canonical checkout or unsafe filesystem aliases.
        """

        target = Path(output).expanduser()
        if not target.is_absolute():
            target = self.paths.primary_root / target
        target = target.absolute()
        try:
            target.relative_to(self.paths.primary_root)
        except ValueError as exc:
            raise StorePathError("derived view path escapes the canonical checkout") from exc
        if target == self.paths.primary_root:
            raise StorePathError("derived view path must name a file")
        _reject_symlink_components(target.parent, allow_missing=True)
        if target.exists() and target.is_symlink():
            raise StorePathError("derived view path cannot be a symlink")
        if target.exists() and target.stat().st_nlink != 1:
            raise StorePathError("derived view path cannot be hard-linked")
        _ensure_derived_parent(target.parent, self.paths.primary_root)
        return publish_bytes(target, content.encode("utf-8"), hard_limit=hard_limit)

    # ----- internal helpers --------------------------------------------------------

    def _provenance_for_store(self, provenance: Mapping[str, Any] | None) -> dict[str, Any]:
        fields = _provenance_fields(provenance)
        git = dict(fields.get("git") or {})
        expected = _repo_identity(self.paths.primary_root)
        supplied = git.get("repository_id", "")
        if supplied and supplied != expected:
            raise StoreError("Git provenance belongs to a different canonical repository")
        if fields.get("origin") != "implementation-progress" or fields.get("intent") != "progress-maintenance":
            raise StoreError("implementation progress provenance has an invalid origin or intent")
        git["repository_id"] = expected
        fields["git"] = git
        return fields

    def _validate_ownership(self, state: Mapping[str, Any]) -> None:
        repository_id = state.get("git", {}).get("repository_id", "")
        expected = _repo_identity(self.paths.primary_root)
        if repository_id and repository_id != expected:
            raise IntegrityError("state Git provenance belongs to a different canonical repository")

    def _validate_event_ownership(self, events: tuple[dict[str, Any], ...]) -> None:
        expected = _repo_identity(self.paths.primary_root)
        for event in events:
            repository_id = event.get("git", {}).get("repository_id", "")
            if repository_id and repository_id != expected:
                raise IntegrityError("journal Git provenance belongs to a different canonical repository")

    def _validate_state_cursor(self, state: Mapping[str, Any], events: tuple[dict[str, Any], ...]) -> None:
        sequence = state.get("last_event_sequence", 0)
        if sequence > len(events):
            raise IntegrityError("state points beyond the end of its verified journal")
        if sequence == 0:
            if state.get("last_event_hash", ""):
                raise IntegrityError("state has a hash without an applied journal sequence")
            return
        if state.get("last_event_hash") != events[sequence - 1].get("record_hash"):
            raise IntegrityError("state last_event_hash does not match its verified journal")

    def _reconcile_state(
        self,
        state: dict[str, Any],
        events: tuple[dict[str, Any], ...],
        *,
        timestamp: str,
    ) -> tuple[dict[str, Any], bool]:
        self._validate_state_cursor(state, events)
        sequence = state["last_event_sequence"]
        if sequence == len(events):
            return state, False
        recovered = dict(state)
        for event in events[sequence:]:
            recovered = self._state_after_event(recovered, event, timestamp=timestamp)
        return validate_state(recovered, expected_plan_id=state["plan_id"]), True

    def _reconstruct_state(
        self,
        plan: PlanPaths,
        events: tuple[dict[str, Any], ...],
        *,
        timestamp: str,
    ) -> dict[str, Any]:
        if not events:
            raise StoreError("cannot reconstruct a plan without journal evidence")
        first = events[0]
        state = new_state(
            plan.plan_id,
            plan_path=first.get("plan_path", ""),
            now=timestamp,
            status=first.get("status", "planned"),
            classification=first.get("classification", "GREEN"),
            phase=first.get("phase", ""),
            git=first.get("git", {}),
            writer_session_id=first.get("writer_session_id", ""),
            model_family=first.get("model_family", "unknown"),
            model_source=first.get("model_source", "unknown"),
            model_verified=first.get("model_verified", False),
            origin=first.get("origin", "implementation-progress"),
            intent=first.get("intent", "progress-maintenance"),
        )
        for event in events:
            state = self._state_after_event(state, event, timestamp=timestamp)
        return validate_state(state, expected_plan_id=plan.plan_id)

    def _read_plan_events(self, plan: PlanPaths, *, reject_partial: bool) -> Any:
        try:
            result = read_jsonl(
                plan.events,
                lambda value: validate_event(value, expected_plan_id=plan.plan_id),
                label=f"events for {plan.plan_id}",
            )
        except CorruptRecordError as exc:
            # A malformed journal is an integrity failure, not an absent plan;
            # callers must preserve the bytes and perform explicit repair.
            raise IntegrityError(str(exc)) from exc
        if reject_partial and result.partial_final_line:
            raise IntegrityError("plan journal has an incomplete final line; explicit repair is required")
        self._validate_sequence_and_hashes(result.records, plan_id=plan.plan_id)
        self._validate_event_ownership(result.records)
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
        state_patch: Mapping[str, Any] | None = None,
        operation_payload: Mapping[str, Any] | None = None,
        provenance: Mapping[str, Any] | None = None,
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
            "state_patch": dict(state_patch or {}),
            "operation_payload_hash": digest(operation_payload or _event_payload_from_fields(event)),
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
        fields = self._provenance_for_store(provenance)
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
            "operation_payload_hash": digest(
                {
                    "kind": "loose_commit_recorded",
                    "summary": summary,
                    "references": references,
                    "evidence_codes": evidence_codes,
                }
            ),
            "state_semantic_hash": "",
            "previous_event_hash": previous_event_hash,
            "record_hash": "",
        }
        event["record_hash"] = event_record_hash(validate_event(event, unplanned=True, allow_unhashed=True))
        return validate_event(event, unplanned=True)

    @staticmethod
    def _state_after_event(state: Mapping[str, Any], event: Mapping[str, Any], *, timestamp: str) -> dict[str, Any]:
        result = dict(state)
        # The snapshot hash is derived after applying the journal record.  Do
        # not carry the predecessor's digest into the next candidate.
        result["semantic_hash"] = ""
        result.update(
            {
                "generation": int(state.get("generation", 0)) + 1,
                "last_operation_id": event["operation_id"],
                "last_event_sequence": event["sequence"],
                "last_event_hash": event["record_hash"],
                "updated_at": timestamp,
            }
        )
        patch = event.get("state_patch") or {}
        if patch:
            result.update(patch)
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
        return validate_state(result, expected_plan_id=event.get("plan_id") or result.get("plan_id"))

    @staticmethod
    def _apply_update(state: Mapping[str, Any], updates: Mapping[str, Any], *, kind: str, summary: str, next_action: str) -> dict[str, Any]:
        if not isinstance(updates, Mapping):
            raise SchemaError("state_update must be a mapping")
        result = dict(state)
        result["semantic_hash"] = ""
        for key, value in updates.items():
            if key in {"schema_version", "plan_id", "semantic_hash", "generation", "last_operation_id", "last_event_sequence", "last_event_hash", "created_at", "updated_at"}:
                raise SchemaError(f"{key} is derived and cannot be directly updated")
            if key == "git" and isinstance(value, Mapping):
                git_update = dict(value)
                existing_repository_id = (result.get("git") or {}).get("repository_id", "")
                if existing_repository_id and "repository_id" not in git_update:
                    git_update["repository_id"] = existing_repository_id
                result[key] = git_update
            else:
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
            left_hash = existing.get("operation_payload_hash", "")
            right_hash = candidate_event.get("operation_payload_hash", "")
            if left_hash and right_hash:
                if left_hash != right_hash:
                    raise IdempotencyError(f"operation_id {operation} was reused with a different payload")
                return
            left = {
                key: value
                for key, value in existing.items()
                if key not in {
                    "event_id",
                    "timestamp",
                    "record_hash",
                    "state_semantic_hash",
                    "operation_payload_hash",
                    "status",
                    "classification",
                    "phase",
                    "plan_path",
                    "git",
                    "writer_session_id",
                    "model_family",
                    "model_source",
                    "model_verified",
                    "origin",
                    "intent",
                }
            }
            right = {
                key: value
                for key, value in candidate_event.items()
                if key not in {
                    "event_id",
                    "timestamp",
                    "record_hash",
                    "state_semantic_hash",
                    "operation_payload_hash",
                    "status",
                    "classification",
                    "phase",
                    "plan_path",
                    "git",
                    "writer_session_id",
                    "model_family",
                    "model_source",
                    "model_verified",
                    "origin",
                    "intent",
                }
            }
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
        return validate_operation_id(value)
    return "op-" + uuid.uuid4().hex


def _ensure_derived_parent(path: Path, primary_root: Path) -> None:
    """Create derived-view parents without changing the checkout mode."""

    _reject_symlink_components(path, allow_missing=True)
    missing: list[Path] = []
    current = path
    while current != primary_root and not current.exists():
        missing.append(current)
        current = current.parent
    try:
        current.relative_to(primary_root)
    except ValueError as exc:
        raise StorePathError("derived view parent escapes the canonical checkout") from exc
    directory_stat(current)
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)
        directory_stat(directory)
        directory.chmod(0o700)


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


def _material_state_patch(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    include_all: bool = False,
) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for key in STATE_PATCH_KEYS:
        if include_all or before.get(key) != after.get(key):
            patch[key] = after.get(key)
    return patch


def _event_payload_from_fields(event: Mapping[str, Any]) -> dict[str, Any]:
    """Return a stable fallback payload for manually-created current events."""

    return {
        "kind": event.get("kind", ""),
        "summary": event.get("summary", ""),
        "reason": event.get("reason", ""),
        "next_action": event.get("next_action", ""),
        "references": event.get("references", []),
        "evidence_codes": event.get("evidence_codes", []),
        "state_patch": event.get("state_patch", {}),
    }


def _registration_operation_payload(
    state: Mapping[str, Any],
    *,
    summary: str = "Plan registered",
    reason: str = "",
    references: list[str] | None = None,
    evidence_codes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "kind": "started",
        "summary": summary,
        "reason": reason,
        "references": list(references or []),
        "evidence_codes": list(evidence_codes or []),
        "plan_path": state.get("plan_path", ""),
        "status": state.get("status", "planned"),
        "classification": state.get("classification", "GREEN"),
        "phase": state.get("phase", ""),
        "objective": state.get("objective", ""),
        "next_action": state.get("next_action", ""),
        "git": state.get("git", {}),
        "model_family": state.get("model_family", "unknown"),
        "model_source": state.get("model_source", "unknown"),
        "model_verified": state.get("model_verified", False),
    }


def _record_operation_payload(
    *,
    kind: str,
    summary: str,
    reason: str,
    next_action: str,
    references: list[str] | None,
    evidence_codes: list[str] | None,
    state_update: Mapping[str, Any] | None,
    provenance: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "summary": summary,
        "reason": reason,
        "next_action": next_action,
        "references": list(references or []),
        "evidence_codes": list(evidence_codes or []),
        "state_update": dict(state_update or {}),
        "provenance": dict(provenance or {}),
    }
