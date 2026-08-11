"""Crash-replayable v4 control state inside the implementation store.

This is an ``execution/`` namespace below the existing canonical plan root,
not a second human-facing progress surface.  It reuses the implementation
store's no-follow locks, bounded readers, append/fsync journal, and atomic
snapshot publication.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import hashlib
from math import isfinite
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping

from .convergent_contracts import (
    MAX_EVENT_BYTES,
    MAX_STATE_BYTES,
    ContractError,
    FORBIDDEN_KEY_TOKENS,
    FORBIDDEN_KEYS,
    make_event,
    state_hash,
    validate_event,
    validate_state,
    SHA256_RE,
    digest_value,
    digest_text,
)
from .convergent_reducer import AMEND_ELIGIBLE_PHASES, Reduction, TransitionRequest, reduce_state
from .decision_packet import AmendmentApproval, DecisionAmendment, DecisionPacketError
from .execution_policy import ExecutionPolicy, assert_policy_compatible
from .goal_compiler import GoalCompileError, compile_goals
from .implementation_store import ImplementationStore
from .implementation_store.io import (
    CorruptRecordError,
    WriteMetadata,
    append_jsonl,
    locked_file,
    publish_json,
    read_json,
    read_jsonl,
)
from .implementation_store.paths import ensure_directory_chain, ensure_store_layout
from .redaction import is_red


MAX_JOURNAL_BYTES = 8 * 1024 * 1024
MAX_EVENTS = 4096
MAX_PLAN_BYTES = 1 * 1024 * 1024


class ConvergentStoreError(RuntimeError):
    """Base error for v4 execution persistence."""


class ConvergentIntegrityError(ConvergentStoreError):
    """Journal/state evidence is corrupt, tampered, incomplete, or out of order."""


class ConvergentIdempotencyError(ConvergentStoreError):
    """One operation ID was retried with changed material input."""


@dataclass(frozen=True)
class ExecutionPaths:
    root: Path
    initial: Path
    state: Path
    events: Path
    state_lock: Path
    goals: Path
    aristotle_evidence: Path
    decision_packet: Path
    findings: Path
    final_audit: Path
    evidence_manifest: Path
    handoff: Path
    amendments: Path
    amendment_approvals: Path
    tool_results: Path
    active_epoch: Path
    epoch_lock: Path
    rotation_pending: Path


@dataclass(frozen=True)
class ConvergentStoreResult:
    changed: bool
    state: Mapping[str, Any] | None = None
    event: Mapping[str, Any] | None = None
    metadata: WriteMetadata = WriteMetadata()
    reason: str = ""
    replayed: bool = False


class ConvergentStore:
    def __init__(
        self,
        progress: ImplementationStore,
        policy: ExecutionPolicy,
        *,
        checkout_head_digest: str = "",
    ) -> None:
        self.progress = progress
        self.policy = policy
        if checkout_head_digest and not SHA256_RE.fullmatch(checkout_head_digest):
            raise ConvergentStoreError("checkout HEAD binding must be a sha256 digest")
        self.checkout_head_digest = checkout_head_digest

    def paths(self, plan_id: str) -> ExecutionPaths:
        plan = self.progress.plan_paths(plan_id)
        root = plan.root / "execution"
        return ExecutionPaths(
            root=root,
            initial=root / "initial.json",
            state=root / "state.json",
            events=root / "events.jsonl",
            state_lock=root / "state.lock",
            goals=root / "goals.json",
            aristotle_evidence=root / "aristotle-evidence.json",
            decision_packet=root / "decision-packet.json",
            findings=root / "findings.json",
            final_audit=root / "final-audit.json",
            evidence_manifest=root / "evidence-manifest.json",
            handoff=root / "handoff.json",
            amendments=root / "amendments.jsonl",
            amendment_approvals=root / "amendment-approvals.jsonl",
            tool_results=root / "tool-results.jsonl",
            active_epoch=root / "active-epoch.json",
            epoch_lock=root / "epoch.lock",
            rotation_pending=root / "epoch-rotation.pending.json",
        )

    def start(self, state: Mapping[str, Any]) -> ConvergentStoreResult:
        try:
            candidate = validate_state(state)
        except ContractError as exc:
            raise ConvergentStoreError("execution state cannot compile the approved serial goal set") from exc
        assert_policy_compatible(candidate["policy_hash"], self.policy)
        plan_id = candidate["plan_id"]
        active_plan = self.progress.read_state(plan_id)
        if active_plan is None:
            raise ConvergentStoreError("canonical implementation plan must be registered before execution state")
        self._validate_plan_provenance(candidate, active_plan)
        goals = self._compile_goal_artifact(candidate, active_plan=active_plan)
        paths = self.paths(plan_id)
        self._ensure_layout(plan_id)
        with self._epoch_state_lock(paths):
            events = self._read_events(paths, reject_partial=True)
            initial = self._read_state_file(paths.initial, label="execution initial")
            snapshot = self._read_state_file(paths.state, label="execution state")
            if events and initial is None:
                raise ConvergentIntegrityError("execution journal exists without an initialized control state")
            if initial is not None:
                if initial != candidate:
                    raise ConvergentStoreError("execution state is already initialized for another task epoch")
                metadata = self._ensure_goal_artifact(paths, goals)
                current, snapshot_current = self._replay(initial, snapshot, events)
                metadata = metadata.plus(self._repair_stale_active_epoch(paths, current, events))
                self._validate_active_epoch(paths, current)
                if not snapshot_current:
                    metadata = metadata.plus(publish_json(paths.state, current, hard_limit=MAX_STATE_BYTES))
                return ConvergentStoreResult(
                    metadata.changed,
                    current,
                    metadata=metadata,
                    reason="idempotent start" if snapshot_current else "recovered execution snapshot",
                    replayed=not snapshot_current,
                )
            if snapshot is not None:
                raise ConvergentIntegrityError("execution snapshot exists without immutable initial state")
            metadata = publish_json(paths.initial, candidate, hard_limit=MAX_STATE_BYTES)
            metadata = metadata.plus(publish_json(paths.state, candidate, hard_limit=MAX_STATE_BYTES))
            metadata = metadata.plus(self._ensure_goal_artifact(paths, goals))
            return ConvergentStoreResult(True, candidate, metadata=metadata, reason="execution state initialized")

    def start_and_transition(
        self,
        state: Mapping[str, Any],
        request: TransitionRequest,
    ) -> ConvergentStoreResult:
        """Initialize and classify Prompt Boundary under one canonical lock.

        Publication remains journal-first and crash-replayable. A retry after
        any partial publication either completes the same operation or returns
        the already committed event; no second prompt can interleave between
        initialization and boundary classification.
        """

        try:
            candidate = validate_state(state)
        except ContractError as exc:
            raise ConvergentStoreError("execution state cannot compile the approved serial goal set") from exc
        assert_policy_compatible(candidate["policy_hash"], self.policy)
        if request.transition != "BOUNDARY_CLASSIFIED" or request.expected_generation != candidate["generation"]:
            raise ConvergentStoreError("atomic start requires the initial Prompt Boundary transition")
        plan_id = candidate["plan_id"]
        active_plan = self.progress.read_state(plan_id)
        if active_plan is None:
            raise ConvergentStoreError("canonical implementation plan must be registered before execution state")
        self._validate_plan_provenance(candidate, active_plan)
        goals = self._compile_goal_artifact(candidate, active_plan=active_plan)
        paths = self.paths(plan_id)
        self._ensure_layout(plan_id)
        with self._epoch_state_lock(paths):
            events = self._read_events(paths, reject_partial=True)
            initial = self._read_state_file(paths.initial, label="execution initial")
            snapshot = self._read_state_file(paths.state, label="execution state")
            metadata = WriteMetadata()
            if events and initial is None:
                raise ConvergentIntegrityError("execution journal exists without an initialized control state")
            if initial is None:
                if snapshot is not None:
                    raise ConvergentIntegrityError("execution snapshot exists without immutable initial state")
                metadata = metadata.plus(publish_json(paths.initial, candidate, hard_limit=MAX_STATE_BYTES))
                metadata = metadata.plus(publish_json(paths.state, candidate, hard_limit=MAX_STATE_BYTES))
                current = candidate
                snapshot_current = True
            else:
                if initial != candidate:
                    raise ConvergentStoreError("execution state is already initialized for another task epoch")
                current, snapshot_current = self._replay(initial, snapshot, events)
                metadata = metadata.plus(self._repair_stale_active_epoch(paths, current, events))
                self._validate_active_epoch(paths, current)
            metadata = metadata.plus(self._ensure_goal_artifact(paths, goals))
            operation_digest = request.operation_digest()
            prior = next((event for event in events if event["operation_id"] == request.operation_id), None)
            if prior is not None:
                if prior["operation_digest"] != operation_digest:
                    raise ConvergentIdempotencyError("operation ID conflicts with an earlier material payload")
                if not snapshot_current:
                    metadata = metadata.plus(publish_json(paths.state, current, hard_limit=MAX_STATE_BYTES))
                return ConvergentStoreResult(
                    metadata.changed,
                    current,
                    prior,
                    metadata=metadata,
                    reason="idempotent atomic start",
                    replayed=not snapshot_current,
                )
            if current["generation"] != candidate["generation"]:
                raise ConvergentStoreError("initial Prompt Boundary operation is missing from an advanced epoch")
            reduction = reduce_state(current, request, policy=self.policy)
            event = make_event(
                operation_id=request.operation_id,
                operation_digest=reduction.operation_digest,
                sequence=len(events) + 1,
                transition=reduction.transition,
                previous=current,
                current=reduction.state,
                evidence_ids=request.evidence_ids,
                previous_event_hash=events[-1]["event_hash"] if events else "",
                actor_role=request.actor_role,
            )
            metadata = metadata.plus(
                append_jsonl(
                    paths.events,
                    event,
                    hard_limit=MAX_EVENT_BYTES,
                    total_hard_limit=MAX_JOURNAL_BYTES,
                    max_records=MAX_EVENTS,
                    existing_records=len(events),
                )
            )
            metadata = metadata.plus(publish_json(paths.state, reduction.state, hard_limit=MAX_STATE_BYTES))
            if paths.active_epoch.exists():
                metadata = metadata.plus(self._publish_active_epoch(paths, reduction.state, request=request))
            return ConvergentStoreResult(
                True,
                reduction.state,
                event,
                metadata=metadata,
                reason="execution state initialized and classified",
            )

    def rotate_epoch_and_transition(
        self,
        state: Mapping[str, Any],
        request: TransitionRequest,
    ) -> ConvergentStoreResult:
        """Archive the active epoch and atomically start a fresh one.

        Epoch rotation keeps the v4 execution namespace single-writer while
        preserving every prior journal/artifact under ``execution/epochs``.
        The active files are moved only while the state lock is held; a failed
        initialization restores them from the archive before releasing it.
        """

        try:
            candidate = validate_state(state)
        except ContractError as exc:
            raise ConvergentStoreError("execution epoch candidate is invalid") from exc
        if request.transition != "BOUNDARY_CLASSIFIED" or request.expected_generation != candidate["generation"]:
            raise ConvergentStoreError("epoch rotation requires an initial Prompt Boundary transition")
        plan_id = candidate["plan_id"]
        active_plan = self.progress.read_state(plan_id)
        if active_plan is None:
            raise ConvergentStoreError("canonical implementation plan must be registered before epoch rotation")
        self._validate_plan_provenance(candidate, active_plan)
        goals = self._compile_goal_artifact(candidate, active_plan=active_plan)
        paths = self.paths(plan_id)
        self._ensure_layout(plan_id)
        with self._epoch_state_lock(paths):
            initial = self._read_state_file(paths.initial, label="execution initial")
            snapshot = self._read_state_file(paths.state, label="execution state")
            events = self._read_events(paths, reject_partial=True)
            if initial is None:
                if snapshot is not None or events:
                    raise ConvergentIntegrityError("execution epoch lacks immutable active state")
                return self._initialize_boundary_locked(paths, candidate, request, goals, events=())
            current, _snapshot_current = self._replay(initial, snapshot, events)
            self._repair_stale_active_epoch(paths, current, events)
            self._validate_active_epoch(paths, current)
            if current["task_epoch"] == candidate["task_epoch"]:
                prior = next((event for event in events if event["operation_id"] == request.operation_id), None)
                if prior is not None:
                    if prior["operation_digest"] != request.operation_digest():
                        raise ConvergentIdempotencyError("epoch operation ID conflicts with an earlier material payload")
                    return ConvergentStoreResult(False, current, prior, reason="idempotent epoch rotation retry", replayed=True)
                if initial != candidate:
                    raise ConvergentStoreError("epoch retry has a conflicting candidate")
                return self._initialize_boundary_locked(paths, candidate, request, goals, events=events, current=current)
            archive_name = str(candidate["task_id"]).replace(":", "-")
            archive = paths.root / "epochs" / archive_name
            try:
                archive_info = archive.lstat()
            except FileNotFoundError:
                archive_info = None
            if archive_info is not None:
                if (
                    stat.S_ISLNK(archive_info.st_mode)
                    or not stat.S_ISDIR(archive_info.st_mode)
                    or archive_info.st_mode & 0o077
                ):
                    raise ConvergentIntegrityError("task epoch archive is unsafe")
                try:
                    empty_archive = not any(archive.iterdir())
                except OSError as exc:
                    raise ConvergentIntegrityError("task epoch archive cannot be inspected") from exc
                if not empty_archive:
                    raise ConvergentIdempotencyError("task epoch archive already exists")
                # A prior process may have removed the pending marker after
                # restoring the predecessor but before removing this empty
                # directory.  Empty private archives carry no authority and
                # are safe to clean before retrying the same rotation.
                os.rmdir(archive)
            ensure_directory_chain(archive, mode=0o700)
            movable = (
                paths.initial,
                paths.state,
                paths.events,
                paths.goals,
                paths.aristotle_evidence,
                paths.decision_packet,
                paths.findings,
                paths.final_audit,
                paths.evidence_manifest,
                paths.handoff,
                paths.amendments,
                paths.amendment_approvals,
                paths.tool_results,
                paths.active_epoch,
            )
            present_names = {source.name for source in movable if source.exists()}
            marker = {
                "schema_version": 1,
                "archive_name": archive_name,
                "candidate_epoch_id": str(candidate["task_epoch"]),
                "candidate_task_id": str(candidate["task_id"]),
                "operation_id": request.operation_id,
                "operation_digest": request.operation_digest(),
                "previous_state_hash": str(current["state_hash"]),
                "files": list(self._epoch_movable_names()),
                "present_files": sorted(present_names),
            }
            publish_json(paths.rotation_pending, marker, hard_limit=MAX_STATE_BYTES)
            moved: list[tuple[Path, Path]] = []
            try:
                for source in movable:
                    if source.exists():
                        target = archive / source.name
                        os.replace(source, target)
                        moved.append((source, target))
                result = self._initialize_boundary_locked(paths, candidate, request, goals, events=())
                metadata = result.metadata.plus(
                    self._publish_active_epoch(
                        paths,
                        result.state or candidate,
                        request=request,
                        previous_epoch_id=str(current.get("task_epoch") or ""),
                    )
                )
                result = ConvergentStoreResult(
                    result.changed,
                    result.state,
                    result.event,
                    metadata=metadata,
                    reason=result.reason,
                    replayed=result.replayed,
                )
                os.unlink(paths.rotation_pending)
                return result
            except Exception:
                for source, target in reversed(moved):
                    if target.exists():
                        # A failure can occur after the candidate has already
                        # published a replacement file (especially the active
                        # pointer). Remove that candidate before restoring the
                        # archived predecessor; otherwise the pointer and
                        # state files can describe different epochs.
                        if source.exists():
                            os.unlink(source)
                        os.replace(target, source)
                for source in movable:
                    if source.name not in present_names and source.exists():
                        # The predecessor did not contain this file.  It can
                        # only be a candidate-only publication from the
                        # failed rotation and must not leak into the restored
                        # epoch.
                        os.unlink(source)
                if archive.exists() and not any(archive.iterdir()):
                    os.rmdir(archive)
                if paths.rotation_pending.exists():
                    os.unlink(paths.rotation_pending)
                raise

    def _initialize_boundary_locked(
        self,
        paths: ExecutionPaths,
        candidate: Mapping[str, Any],
        request: TransitionRequest,
        goals: Mapping[str, Any],
        *,
        events: tuple[Mapping[str, Any], ...],
        current: Mapping[str, Any] | None = None,
    ) -> ConvergentStoreResult:
        metadata = WriteMetadata()
        if current is None:
            metadata = metadata.plus(publish_json(paths.initial, candidate, hard_limit=MAX_STATE_BYTES))
            metadata = metadata.plus(publish_json(paths.state, candidate, hard_limit=MAX_STATE_BYTES))
            current_state = dict(candidate)
        else:
            current_state = dict(current)
        metadata = metadata.plus(self._ensure_goal_artifact(paths, goals))
        prior = next((event for event in events if event["operation_id"] == request.operation_id), None)
        operation_digest = request.operation_digest()
        if prior is not None:
            if prior["operation_digest"] != operation_digest:
                raise ConvergentIdempotencyError("operation ID conflicts with an earlier material payload")
            return ConvergentStoreResult(False, current_state, prior, metadata=metadata, reason="idempotent epoch start")
        reduction = reduce_state(current_state, request, policy=self.policy)
        event = make_event(
            operation_id=request.operation_id,
            operation_digest=reduction.operation_digest,
            sequence=len(events) + 1,
            transition=reduction.transition,
            previous=current_state,
            current=reduction.state,
            evidence_ids=request.evidence_ids,
            previous_event_hash=events[-1]["event_hash"] if events else "",
            actor_role=request.actor_role,
        )
        metadata = metadata.plus(
            append_jsonl(
                paths.events,
                event,
                hard_limit=MAX_EVENT_BYTES,
                total_hard_limit=MAX_JOURNAL_BYTES,
                max_records=MAX_EVENTS,
                existing_records=len(events),
            )
        )
        metadata = metadata.plus(publish_json(paths.state, reduction.state, hard_limit=MAX_STATE_BYTES))
        return ConvergentStoreResult(True, reduction.state, event, metadata=metadata, reason="execution epoch rotated and classified")

    def read_current(self, plan_id: str, *, authoritative: bool = False) -> ConvergentStoreResult:
        paths = self.paths(plan_id)
        self._ensure_layout(plan_id)
        # Reads participate in the same namespace protocol as mutations.  In
        # particular, a non-authoritative read must not observe the
        # half-moved files of an epoch rotation or race recovery with a
        # writer.  The ``authoritative`` bit only controls partial-tail
        # handling; it does not weaken the lock/recovery boundary.
        with self._epoch_state_lock(paths):
            return self._read_current_unlocked(paths, authoritative=authoritative)

    def _read_current_unlocked(self, paths: ExecutionPaths, *, authoritative: bool) -> ConvergentStoreResult:
        initial = self._read_state_file(paths.initial, label="execution initial")
        snapshot = self._read_state_file(paths.state, label="execution state")
        if initial is None:
            if snapshot is not None or paths.events.exists():
                raise ConvergentIntegrityError("execution state lacks immutable initial evidence")
            return ConvergentStoreResult(False, reason="execution state missing")
        events = self._read_events(paths, reject_partial=authoritative)
        replayed, snapshot_current = self._replay(initial, snapshot, events)
        metadata = self._repair_stale_active_epoch(paths, replayed, events)
        self._validate_active_epoch(paths, replayed)
        self._validate_current_plan_provenance(replayed)
        return ConvergentStoreResult(
            metadata.changed,
            replayed,
            metadata=metadata,
            reason="active epoch repaired" if metadata.changed else "read-only replay",
            replayed=not snapshot_current,
        )

    def transition(self, plan_id: str, request: TransitionRequest) -> ConvergentStoreResult:
        paths = self.paths(plan_id)
        self._ensure_layout(plan_id)
        with self._epoch_state_lock(paths):
            initial = self._read_state_file(paths.initial, label="execution initial")
            if initial is None:
                raise ConvergentStoreError("execution state is not initialized")
            snapshot = self._read_state_file(paths.state, label="execution state")
            events = self._read_events(paths, reject_partial=True)
            current, snapshot_current = self._replay(initial, snapshot, events)
            pointer_metadata = self._repair_stale_active_epoch(paths, current, events)
            self._validate_active_epoch(paths, current)
            assert_policy_compatible(current["policy_hash"], self.policy)
            self._validate_current_plan_provenance(current)
            operation_digest = request.operation_digest()
            previous_operation = next((event for event in events if event["operation_id"] == request.operation_id), None)
            if previous_operation is not None:
                if previous_operation["operation_digest"] != operation_digest:
                    raise ConvergentIdempotencyError("operation ID conflicts with an earlier material payload")
                metadata = pointer_metadata
                if not snapshot_current:
                    metadata = metadata.plus(publish_json(paths.state, current, hard_limit=MAX_STATE_BYTES))
                return ConvergentStoreResult(
                    False,
                    current,
                    previous_operation,
                    metadata=metadata,
                    reason="idempotent retry",
                    replayed=not snapshot_current,
                )

            # Idempotent retries are answered from the journal before checking
            # mutable artifacts.  A later, legitimate packet/triage artifact
            # replacement must not make the already-committed operation look
            # invalid; only a genuinely new operation is bound to the current
            # artifact generation.
            self._validate_transition_artifacts(paths, current, request)
            if request.transition == "POST_TOOL_RESULT_RECORDED" and self.checkout_head_digest:
                if request.head_digest != self.checkout_head_digest:
                    raise ConvergentStoreError("PostTool result HEAD is not bound to the active checkout")

            reduction = reduce_state(current, request, policy=self.policy)
            tool_result_metadata = WriteMetadata()
            if request.transition == "POST_TOOL_RESULT_RECORDED":
                records = self._read_tool_result_records(paths)
                prior_tool = next((row for row in records if row["operation_id"] == request.operation_id), None)
                tool_record = self._tool_result_record(request)
                if prior_tool is not None:
                    if prior_tool["operation_digest"] != tool_record["operation_digest"]:
                        raise ConvergentIdempotencyError("PostTool operation ID conflicts with an earlier result")
                else:
                    tool_result_metadata = append_jsonl(
                        paths.tool_results,
                        tool_record,
                        hard_limit=MAX_EVENT_BYTES,
                        total_hard_limit=MAX_JOURNAL_BYTES,
                        max_records=MAX_EVENTS,
                        existing_records=len(records),
                    )

            event = make_event(
                operation_id=request.operation_id,
                operation_digest=reduction.operation_digest,
                sequence=len(events) + 1,
                transition=reduction.transition,
                previous=current,
                current=reduction.state,
                evidence_ids=request.evidence_ids,
                previous_event_hash=events[-1]["event_hash"] if events else "",
                actor_role=request.actor_role,
            )
            metadata = pointer_metadata.plus(tool_result_metadata).plus(append_jsonl(
                paths.events,
                event,
                hard_limit=MAX_EVENT_BYTES,
                total_hard_limit=MAX_JOURNAL_BYTES,
                max_records=MAX_EVENTS,
                existing_records=len(events),
            ))
            # Journal first: a crash before this snapshot publication is
            # recoverable from immutable initial state plus validated patches.
            metadata = metadata.plus(publish_json(paths.state, reduction.state, hard_limit=MAX_STATE_BYTES))
            if paths.active_epoch.exists():
                metadata = metadata.plus(self._publish_active_epoch(paths, reduction.state, request=request))
            return ConvergentStoreResult(True, reduction.state, event, metadata=metadata, reason="transition committed")

    def _validate_transition_artifacts(
        self,
        paths: ExecutionPaths,
        current: Mapping[str, Any],
        request: TransitionRequest,
    ) -> None:
        """Bind material state transitions to their persisted machine artifact."""

        if request.transition == "AMEND":
            records = self._read_amendment_records(paths)
            matching = [row for row in records if row.get("amendment_fingerprint") == request.amendment_fingerprint]
            if not matching:
                raise ConvergentStoreError("material amendment artifact is missing or unbound")
            if matching[0].get("prior_decision_fingerprint") != current["aristotle"].get("decision_fingerprint"):
                raise ConvergentStoreError("material amendment prior packet fingerprint is stale")
            if matching[0].get("new_decision_fingerprint") != request.decision_fingerprint:
                raise ConvergentStoreError("material amendment does not bind the replacement Decision Packet")
            if matching[0].get("task_epoch") != current.get("task_epoch"):
                raise ConvergentStoreError("material amendment task epoch is stale")
            if (
                matching[0].get("prior_decision_version") != current["aristotle"].get("decision_version")
                or matching[0].get("new_decision_version") != request.decision_version
            ):
                raise ConvergentStoreError("material amendment decision version is stale")
            approvals = self._read_amendment_approvals(paths)
            approval = next(
                (
                    row
                    for row in approvals
                    if row.get("approval_fingerprint") == request.approval_fingerprint
                    and row.get("amendment_fingerprint") == request.amendment_fingerprint
                ),
                None,
            )
            if approval is None or approval.get("actor_role") != "codex-main":
                raise ConvergentStoreError("material amendment Codex main approval artifact is missing")
            self._require_packet_digest(
                paths.decision_packet,
                request.decision_fingerprint,
                current=current,
                expected_version=request.decision_version,
            )
        elif request.transition == "ARISTOTLE_RECORDED":
            if request.tier in {"full", "critical"}:
                self._require_packet_digest(
                    paths.decision_packet,
                    request.decision_fingerprint,
                    current=current,
                    expected_version=request.decision_version,
                )
            else:
                self._require_aristotle_evidence(
                    paths.aristotle_evidence,
                    request.decision_fingerprint,
                    current=current,
                    tier=request.tier,
                    decision_version=request.decision_version,
                )
        elif request.transition == "REVIEW_RECORDED":
            ledger = self._read_finding_ledger(paths.findings)
            if ledger.findings_digest != request.findings_digest or ledger.risk != current["risk"]:
                raise ConvergentStoreError("findings ledger does not match the canonical review risk or digest")
            if tuple(sorted(ledger.accepted_ids)) != tuple(sorted(request.accepted_finding_ids)):
                raise ConvergentStoreError("accepted findings do not match the persisted review ledger")
        elif request.transition == "FINDINGS_TRIAGED":
            ledger = self._read_finding_ledger(paths.findings)
            if ledger.findings_digest != request.findings_digest:
                raise ConvergentStoreError("triage findings ledger digest is stale")
            if tuple(sorted(ledger.accepted_ids)) != tuple(sorted(request.accepted_finding_ids)):
                raise ConvergentStoreError("triage accepted findings do not match the persisted ledger")
        elif request.transition == "EVIDENCE_RECORDED":
            self._require_evidence_manifest(
                paths.evidence_manifest,
                request.evidence_manifest_digest,
                current=current,
                expected_evidence_ids=request.evidence_ids,
            )
            if request.handoff_digest:
                self._require_handoff(
                    paths.handoff,
                    request.handoff_digest,
                    current=current,
                    evidence_manifest_digest=request.evidence_manifest_digest,
                )
        elif request.transition == "FINAL_AUDIT_RECORDED":
            audit = self._read_final_audit(paths.final_audit, current=current)
            if audit.audit_digest != request.final_audit_digest:
                raise ConvergentStoreError("final audit artifact digest is not bound to the transition")
            if request.audit_pass is not audit.passed:
                raise ConvergentStoreError("final audit verdict does not match the typed audit artifact")
            if request.hard_gates_pass is not audit.passed:
                raise ConvergentStoreError("final audit hard-gate verdict does not match the typed audit artifact")
            self._require_decision_evidence(paths, current)
            self._require_completion_evidence(paths, current)
            if current["review"].get("findings_digest"):
                ledger = self._read_finding_ledger(paths.findings)
                if ledger.findings_digest != current["review"]["findings_digest"]:
                    raise ConvergentStoreError("final audit findings ledger is stale")
        elif request.transition == "CLOSE":
            audit = self._read_final_audit(paths.final_audit, current=current)
            if audit.audit_digest != current["completion"].get("final_audit_digest"):
                raise ConvergentStoreError("close is not bound to the current final audit")
            self._require_decision_evidence(paths, current)
            self._require_completion_evidence(paths, current)

    def _read_final_audit(self, path: Path, *, current: Mapping[str, Any] | None = None):
        try:
            from .final_audit import run_final_audit

            payload = read_json(path, lambda value: deepcopy(dict(value)), label="execution final audit", hard_limit=MAX_STATE_BYTES)
            if not isinstance(payload, Mapping):
                raise ConvergentStoreError("final audit artifact is not a typed deterministic audit")
            required = {
                "evidence",
                "audit_digest",
                "packet_fingerprint",
                "plan_digest",
                "policy_hash",
                "evidence_manifest_digest",
                "branch",
                "head_digest",
                "worktree_id",
                "accepted_finding_ids",
                "closed_finding_ids",
            }
            if set(payload) != required:
                raise ConvergentStoreError("final audit artifact metadata is incomplete")
            evidence = payload.get("evidence")
            result = run_final_audit(evidence) if isinstance(evidence, Mapping) else None
            if result is None or payload.get("audit_digest") != result.audit_digest:
                raise ConvergentStoreError("final audit artifact is not a typed deterministic audit")
            for label in ("packet_fingerprint", "plan_digest", "policy_hash", "evidence_manifest_digest", "head_digest"):
                value = payload.get(label)
                if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
                    raise ConvergentStoreError(f"final audit {label} is not a sha256 digest")
            if not isinstance(payload.get("branch"), str) or not payload["branch"]:
                raise ConvergentStoreError("final audit branch evidence is missing")
            if not isinstance(payload.get("worktree_id"), str) or not SHA256_RE.fullmatch(payload["worktree_id"]):
                raise ConvergentStoreError("final audit worktree evidence is missing")
            for label in ("accepted_finding_ids", "closed_finding_ids"):
                values = payload.get(label)
                if not isinstance(values, list) or any(not isinstance(item, str) or not item for item in values):
                    raise ConvergentStoreError(f"final audit {label} is invalid")
            if current is not None:
                if not self.checkout_head_digest:
                    raise ConvergentStoreError("final audit requires an independently resolved checkout HEAD")
                identity = current.get("task_identity") if isinstance(current.get("task_identity"), Mapping) else {}
                expected = {
                    "packet_fingerprint": current.get("aristotle", {}).get("decision_fingerprint"),
                    "plan_digest": current.get("plan_digest"),
                    "policy_hash": current.get("policy_hash"),
                    "evidence_manifest_digest": current.get("completion", {}).get("evidence_manifest_digest"),
                    "branch": identity.get("branch"),
                    "worktree_id": identity.get("worktree_id"),
                }
                if any(payload.get(label) != value for label, value in expected.items()):
                    raise ConvergentStoreError("final audit artifact is not bound to the canonical state")
                if payload.get("head_digest") != self.checkout_head_digest:
                    raise ConvergentStoreError("final audit artifact does not bind the actual checkout HEAD")
                accepted = tuple(sorted(payload.get("accepted_finding_ids", [])))
                closed = tuple(sorted(payload.get("closed_finding_ids", [])))
                findings_digest = current.get("review", {}).get("findings_digest")
                if findings_digest:
                    ledger = self._read_finding_ledger(path.parent / "findings.json")
                    if ledger.findings_digest != findings_digest:
                        raise ConvergentStoreError("final audit findings ledger is stale")
                    ledger_ids = {finding.finding_id for finding in ledger.findings}
                    if accepted != tuple(sorted(ledger.accepted_ids)):
                        raise ConvergentStoreError("final audit accepted findings differ from the persisted ledger")
                    if set(closed) - ledger_ids:
                        raise ConvergentStoreError("final audit closes findings absent from the persisted ledger")
                if set(accepted) - set(closed):
                    raise ConvergentStoreError("final audit leaves accepted findings open")
            return result
        except (CorruptRecordError, TypeError, ValueError, KeyError) as exc:
            raise ConvergentStoreError("final audit artifact is not a typed deterministic audit") from exc

    @staticmethod
    def _read_finding_ledger(path: Path):
        try:
            from .convergent_review import FindingLedger, ReviewFinding

            payload = read_json(path, lambda value: deepcopy(dict(value)), label="execution findings", hard_limit=MAX_STATE_BYTES)
            rows = payload.get("findings") if isinstance(payload, Mapping) else None
            if not isinstance(payload, Mapping) or not isinstance(rows, list):
                raise ConvergentStoreError("findings artifact is not a typed review ledger")
            return FindingLedger.create(
                risk=str(payload.get("risk") or ""),
                review_pass=int(payload.get("review_pass")),
                review_owner=str(payload.get("review_owner") or ""),
                findings=tuple(ReviewFinding.from_mapping(row) for row in rows),
            )
        except (CorruptRecordError, TypeError, ValueError, KeyError) as exc:
            raise ConvergentStoreError("findings artifact is not a typed review ledger") from exc

    def _read_amendment_records(self, paths: ExecutionPaths) -> tuple[dict[str, Any], ...]:
        try:
            result = read_jsonl(
                paths.amendments,
                lambda value: DecisionAmendment.from_mapping(value).as_dict(),
                label="execution amendments",
                total_hard_limit=MAX_STATE_BYTES,
                max_records=self.policy.amendment_budget,
            )
        except (CorruptRecordError, DecisionPacketError) as exc:
            raise ConvergentIntegrityError("execution amendment journal is invalid") from exc
        if result.partial_final_line:
            raise ConvergentIntegrityError("execution amendment journal has an incomplete final line")
        return result.records

    def _read_amendment_approvals(self, paths: ExecutionPaths) -> tuple[dict[str, Any], ...]:
        try:
            result = read_jsonl(
                paths.amendment_approvals,
                lambda value: AmendmentApproval.from_mapping(value).as_dict(),
                label="execution amendment approvals",
                total_hard_limit=MAX_STATE_BYTES,
                max_records=self.policy.amendment_budget,
            )
        except (CorruptRecordError, DecisionPacketError) as exc:
            raise ConvergentIntegrityError("execution amendment approval journal is invalid") from exc
        if result.partial_final_line:
            raise ConvergentIntegrityError("execution amendment approval journal has an incomplete final line")
        return result.records

    @staticmethod
    def _require_packet_digest(
        path: Path,
        expected: str,
        *,
        current: Mapping[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> None:
        try:
            from .decision_packet import DecisionPacket

            payload = read_json(path, lambda value: deepcopy(dict(value)), label="execution decision packet", hard_limit=MAX_STATE_BYTES)
            packet = DecisionPacket.from_mapping(payload) if isinstance(payload, Mapping) else None
        except (CorruptRecordError, DecisionPacketError, TypeError, ValueError) as exc:
            raise ConvergentStoreError("Decision Packet artifact is missing or invalid") from exc
        if packet is None or packet.analysis_fingerprint != expected:
            raise ConvergentStoreError("Decision Packet fingerprint is not bound to the transition")
        if current is not None and packet.task_epoch != current.get("task_epoch"):
            raise ConvergentStoreError("Decision Packet task epoch is not bound to the transition")
        if expected_version is not None and packet.decision_version != expected_version:
            raise ConvergentStoreError("Decision Packet version is not bound to the transition")

    @staticmethod
    def _require_aristotle_evidence(
        path: Path,
        expected: str,
        *,
        current: Mapping[str, Any],
        tier: str,
        decision_version: int,
    ) -> None:
        try:
            from .convergent_aristotle import AristotleEvidence

            payload = read_json(path, lambda value: deepcopy(dict(value)), label="execution Aristotle evidence", hard_limit=MAX_STATE_BYTES)
            evidence = AristotleEvidence.from_mapping(payload) if isinstance(payload, Mapping) else None
        except (CorruptRecordError, TypeError, ValueError) as exc:
            raise ConvergentStoreError("typed Aristotle evidence is missing or invalid") from exc
        if (
            evidence is None
            or evidence.evidence_digest != expected
            or evidence.task_epoch != current.get("task_epoch")
            or evidence.tier != tier
            or evidence.decision_version != decision_version
        ):
            raise ConvergentStoreError("typed Aristotle evidence is not bound to the transition")

    @staticmethod
    def _require_decision_evidence(paths: ExecutionPaths, current: Mapping[str, Any]) -> None:
        """Validate either a typed packet or the deterministic low-risk record."""

        aristotle = current.get("aristotle") if isinstance(current.get("aristotle"), Mapping) else {}
        tier = str(aristotle.get("tier") or "")
        expected = str(aristotle.get("decision_fingerprint") or "")
        if tier in {"full", "critical"} or int(aristotle.get("amendments") or 0) > 0:
            ConvergentStore._require_packet_digest(
                paths.decision_packet,
                expected,
                current=current,
                expected_version=int(aristotle.get("decision_version") or 0),
            )
            return
        ConvergentStore._require_aristotle_evidence(
            paths.aristotle_evidence,
            expected,
            current=current,
            tier=tier,
            decision_version=int(aristotle.get("decision_version") or 0),
        )

    @staticmethod
    def _validate_evidence_manifest_payload(
        payload: Mapping[str, Any],
        *,
        current: Mapping[str, Any],
        exact_generation: bool = True,
    ) -> None:
        required = {
            "schema_version",
            "task_id",
            "task_epoch",
            "plan_digest",
            "decision_fingerprint",
            "state_generation",
            "evidence_ids",
        }
        if set(payload) != required or payload.get("schema_version") != 1:
            raise ConvergentStoreError("evidence manifest schema is invalid")
        generation = payload.get("state_generation")
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
            raise ConvergentStoreError("evidence manifest generation is invalid")
        if exact_generation and generation != current.get("generation"):
            raise ConvergentStoreError("evidence manifest generation is stale")
        if not exact_generation and generation > int(current.get("generation") or 0):
            raise ConvergentStoreError("evidence manifest generation is from the future")
        expected = {
            "task_id": current.get("task_id"),
            "task_epoch": current.get("task_epoch"),
            "plan_digest": current.get("plan_digest"),
            "decision_fingerprint": current.get("aristotle", {}).get("decision_fingerprint"),
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            raise ConvergentStoreError("evidence manifest is not bound to the canonical state")
        evidence_ids = payload.get("evidence_ids")
        if (
            not isinstance(evidence_ids, list)
            or len(evidence_ids) > 64
            or any(not isinstance(item, str) or not item or len(item) > 180 for item in evidence_ids)
            or len(set(evidence_ids)) != len(evidence_ids)
        ):
            raise ConvergentStoreError("evidence manifest identifiers are invalid")

    @staticmethod
    def _validate_handoff_payload(
        payload: Mapping[str, Any],
        *,
        current: Mapping[str, Any],
        exact_generation: bool = True,
    ) -> None:
        required = {
            "schema_version",
            "task_id",
            "task_epoch",
            "plan_digest",
            "decision_fingerprint",
            "state_generation",
            "evidence_manifest_digest",
        }
        if set(payload) != required or payload.get("schema_version") != 1:
            raise ConvergentStoreError("handoff schema is invalid")
        generation = payload.get("state_generation")
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
            raise ConvergentStoreError("handoff generation is invalid")
        if exact_generation and generation != current.get("generation"):
            raise ConvergentStoreError("handoff generation is stale")
        if not exact_generation and generation > int(current.get("generation") or 0):
            raise ConvergentStoreError("handoff generation is from the future")
        expected = {
            "task_id": current.get("task_id"),
            "task_epoch": current.get("task_epoch"),
            "plan_digest": current.get("plan_digest"),
            "decision_fingerprint": current.get("aristotle", {}).get("decision_fingerprint"),
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            raise ConvergentStoreError("handoff is not bound to the canonical state")
        manifest_digest = payload.get("evidence_manifest_digest")
        if not isinstance(manifest_digest, str) or not SHA256_RE.fullmatch(manifest_digest):
            raise ConvergentStoreError("handoff evidence manifest digest is invalid")

    @staticmethod
    def _require_evidence_manifest(
        path: Path,
        expected: str,
        *,
        current: Mapping[str, Any],
        expected_evidence_ids: tuple[str, ...] | None = None,
    ) -> None:
        try:
            payload = read_json(path, lambda value: deepcopy(dict(value)), label="execution evidence manifest", hard_limit=MAX_STATE_BYTES)
        except (CorruptRecordError, TypeError, ValueError) as exc:
            raise ConvergentStoreError("persisted evidence manifest is missing or invalid") from exc
        if not isinstance(payload, Mapping):
            raise ConvergentStoreError("persisted evidence manifest is missing or invalid")
        ConvergentStore._validate_evidence_manifest_payload(payload, current=current, exact_generation=False)
        if digest_value(payload) != expected:
            raise ConvergentStoreError("evidence manifest digest is not bound to persisted evidence")
        if expected_evidence_ids is not None and tuple(payload["evidence_ids"]) != tuple(expected_evidence_ids):
            raise ConvergentStoreError("evidence manifest identifiers do not match the transition")

    @staticmethod
    def _require_handoff(
        path: Path,
        expected: str,
        *,
        current: Mapping[str, Any],
        evidence_manifest_digest: str,
    ) -> None:
        try:
            payload = read_json(path, lambda value: deepcopy(dict(value)), label="execution handoff", hard_limit=MAX_STATE_BYTES)
        except (CorruptRecordError, TypeError, ValueError) as exc:
            raise ConvergentStoreError("persisted handoff is missing or invalid") from exc
        if not isinstance(payload, Mapping):
            raise ConvergentStoreError("persisted handoff is missing or invalid")
        ConvergentStore._validate_handoff_payload(payload, current=current, exact_generation=False)
        if digest_value(payload) != expected or payload.get("evidence_manifest_digest") != evidence_manifest_digest:
            raise ConvergentStoreError("handoff digest is not bound to persisted evidence")

    def _require_completion_evidence(self, paths: ExecutionPaths, current: Mapping[str, Any]) -> None:
        completion = current.get("completion") if isinstance(current.get("completion"), Mapping) else {}
        manifest_digest = str(completion.get("evidence_manifest_digest") or "")
        handoff_digest = str(completion.get("handoff_digest") or "")
        if not manifest_digest or completion.get("handoff_published") is not True or not handoff_digest:
            raise ConvergentStoreError("completion evidence artifacts are incomplete")
        if paths.evidence_manifest.exists():
            self._require_evidence_manifest(paths.evidence_manifest, manifest_digest, current=current)
        else:
            records = self._read_tool_result_records(paths)
            if not any(
                row.get("task_id") == current.get("task_id")
                and row.get("task_epoch") == current.get("task_epoch")
                and row.get("evidence_manifest_digest") == manifest_digest
                for row in records
            ):
                raise ConvergentStoreError("completion evidence has no persisted manifest or tool-result record")
        self._require_handoff(
            paths.handoff,
            handoff_digest,
            current=current,
            evidence_manifest_digest=manifest_digest,
        )

    @staticmethod
    def _require_artifact_digest(path: Path, expected: str, label: str) -> None:
        try:
            payload = read_json(path, lambda value: deepcopy(dict(value)), label=f"execution {label}", hard_limit=MAX_STATE_BYTES)
        except CorruptRecordError as exc:
            raise ConvergentIntegrityError(str(exc)) from exc
        if not isinstance(payload, Mapping):
            raise ConvergentStoreError(f"{label} artifact is missing")
        if label == "findings":
            try:
                from .convergent_review import FindingLedger, ReviewFinding

                rows = payload.get("findings")
                ledger = FindingLedger.create(
                    risk=str(payload.get("risk") or ""),
                    review_pass=int(payload.get("review_pass")),
                    review_owner=str(payload.get("review_owner") or ""),
                    findings=tuple(ReviewFinding.from_mapping(row) for row in rows) if isinstance(rows, list) else (),
                )
            except (TypeError, ValueError, KeyError) as exc:
                raise ConvergentStoreError("findings artifact is not a typed review ledger") from exc
            if ledger.findings_digest != expected or payload.get("findings_digest") != ledger.findings_digest:
                raise ConvergentStoreError("findings artifact digest is not bound to the transition")
            return
        if label == "final audit":
            try:
                from .final_audit import run_final_audit

                evidence = payload.get("evidence")
                result = run_final_audit(evidence) if isinstance(evidence, Mapping) else None
            except (TypeError, ValueError, KeyError) as exc:
                raise ConvergentStoreError("final audit artifact is not a typed deterministic audit") from exc
            if result is None or result.audit_digest != expected or payload.get("audit_digest") != result.audit_digest:
                raise ConvergentStoreError("final audit artifact digest is not bound to the transition")
            return
        raise ConvergentStoreError(f"unsupported transition artifact {label}")

    def replay(self, plan_id: str) -> ConvergentStoreResult:
        paths = self.paths(plan_id)
        self._ensure_layout(plan_id)
        with self._epoch_state_lock(paths):
            initial = self._read_state_file(paths.initial, label="execution initial")
            if initial is None:
                return ConvergentStoreResult(False, reason="execution state missing")
            snapshot = self._read_state_file(paths.state, label="execution state")
            events = self._read_events(paths, reject_partial=True)
            current, snapshot_current = self._replay(initial, snapshot, events)
            pointer_metadata = self._repair_stale_active_epoch(paths, current, events)
            self._validate_active_epoch(paths, current)
            if snapshot_current:
                return ConvergentStoreResult(
                    pointer_metadata.changed,
                    current,
                    metadata=pointer_metadata,
                    reason="active epoch repaired" if pointer_metadata.changed else "already current",
                )
            metadata = pointer_metadata.plus(publish_json(paths.state, current, hard_limit=MAX_STATE_BYTES))
            return ConvergentStoreResult(True, current, metadata=metadata, reason="journal replayed", replayed=True)

    def publish_artifact(self, plan_id: str, name: str, payload: Mapping[str, Any]) -> WriteMetadata:
        """Publish one bounded content-safe machine artifact in execution/."""

        paths = self.paths(plan_id)
        # goals.json has a single owner: the deterministic compiler in start().
        allowed = {
            "aristotle-evidence": paths.aristotle_evidence,
            "decision-packet": paths.decision_packet,
            "findings": paths.findings,
            "final-audit": paths.final_audit,
            "evidence-manifest": paths.evidence_manifest,
            "handoff": paths.handoff,
        }
        if name not in allowed:
            raise ConvergentStoreError("unsupported execution artifact")
        self._ensure_layout(plan_id)
        encoded = deepcopy(dict(payload))
        _assert_safe_artifact(encoded)
        with self._epoch_state_lock(paths):
            initial = self._read_state_file(paths.initial, label="execution initial")
            if initial is None:
                raise ConvergentStoreError("execution state is not initialized")
            snapshot = self._read_state_file(paths.state, label="execution state")
            events = self._read_events(paths, reject_partial=True)
            current, _snapshot_current = self._replay(initial, snapshot, events)
            self._validate_current_plan_provenance(current)
            if current["phase"] == "close" or current["status"] == "closed":
                raise ConvergentStoreError("execution artifacts are immutable after close")
            if name == "decision-packet" and current["aristotle"].get("decision_fingerprint"):
                # A packet is frozen once Aristotle has been recorded.  The
                # only legal replacement is the one amendment already
                # appended for the current packet, under the same state lock.
                amendments = self._read_amendment_records(paths)
                pending_amendment = any(
                    row.get("prior_decision_fingerprint") == current["aristotle"].get("decision_fingerprint")
                    and row.get("prior_decision_version") == current["aristotle"].get("decision_version")
                    and row.get("task_epoch") == current.get("task_epoch")
                    and row.get("new_decision_fingerprint")
                    for row in amendments
                )
                if current["phase"] not in AMEND_ELIGIBLE_PHASES or not pending_amendment:
                    raise ConvergentStoreError("Decision Packet artifact is immutable without a material amendment")
            if name == "findings" and current["review"].get("findings_digest"):
                # Review records the pending ledger before triage. Exactly one
                # CAS-bound replacement is allowed while the state is in
                # finding_triage, and only when the replacement preserves all
                # finding identity/metadata while resolving every status.
                if current["phase"] != "finding_triage":
                    raise ConvergentStoreError("findings artifact is immutable after review recording")
                self._validate_triaged_finding_replacement(paths.findings, encoded, current["review"]["findings_digest"])
            if name == "final-audit" and current["completion"].get("final_audit_digest"):
                raise ConvergentStoreError("final-audit artifact is immutable after audit recording")
            if name == "aristotle-evidence" and current["aristotle"].get("decision_fingerprint"):
                raise ConvergentStoreError("Aristotle evidence is immutable after analysis recording")
            if name == "evidence-manifest":
                self._validate_evidence_manifest_payload(encoded, current=current)
            if name == "handoff":
                self._validate_handoff_payload(encoded, current=current)
            return publish_json(allowed[name], encoded, hard_limit=MAX_STATE_BYTES)

    @staticmethod
    def _validate_triaged_finding_replacement(path: Path, encoded: Mapping[str, Any], prior_digest: str) -> None:
        try:
            from .convergent_review import FindingLedger, ReviewFinding

            old_payload = read_json(path, lambda value: deepcopy(dict(value)), label="execution findings", hard_limit=MAX_STATE_BYTES)
            old_rows = old_payload.get("findings") if isinstance(old_payload, Mapping) else None
            new_rows = encoded.get("findings") if isinstance(encoded, Mapping) else None
            old_ledger = FindingLedger.create(
                risk=str(old_payload.get("risk") or ""),
                review_pass=int(old_payload.get("review_pass")),
                review_owner=str(old_payload.get("review_owner") or ""),
                findings=tuple(ReviewFinding.from_mapping(row) for row in old_rows) if isinstance(old_rows, list) else (),
            )
            new_ledger = FindingLedger.create(
                risk=str(encoded.get("risk") or ""),
                review_pass=int(encoded.get("review_pass")),
                review_owner=str(encoded.get("review_owner") or ""),
                findings=tuple(ReviewFinding.from_mapping(row) for row in new_rows) if isinstance(new_rows, list) else (),
            )
        except (CorruptRecordError, TypeError, ValueError, KeyError) as exc:
            raise ConvergentStoreError("triaged findings replacement is not a typed review ledger") from exc
        if old_ledger.findings_digest != prior_digest:
            raise ConvergentStoreError("triaged findings replacement prior digest is stale")
        if (old_ledger.risk, old_ledger.review_pass, old_ledger.review_owner) != (
            new_ledger.risk,
            new_ledger.review_pass,
            new_ledger.review_owner,
        ):
            raise ConvergentStoreError("triaged findings replacement changed ledger metadata")
        if len(old_ledger.findings) != len(new_ledger.findings):
            raise ConvergentStoreError("triaged findings replacement changed finding cardinality")
        old_by_id = {item.finding_id: item for item in old_ledger.findings}
        new_by_id = {item.finding_id: item for item in new_ledger.findings}
        if set(old_by_id) != set(new_by_id) or any(
            (old_by_id[item].severity, old_by_id[item].location, old_by_id[item].root_cause, old_by_id[item].impact, old_by_id[item].evidence_ids, old_by_id[item].recommendation)
            != (new_by_id[item].severity, new_by_id[item].location, new_by_id[item].root_cause, new_by_id[item].impact, new_by_id[item].evidence_ids, new_by_id[item].recommendation)
            for item in old_by_id
        ):
            raise ConvergentStoreError("triaged findings replacement changed finding identity")
        if any(item.triage_status == "pending" for item in new_ledger.findings):
            raise ConvergentStoreError("triaged findings replacement must resolve every finding")

    def append_amendment(self, plan_id: str, amendment: DecisionAmendment) -> WriteMetadata:
        """Append the single budgeted material amendment with ID idempotency."""

        if not isinstance(amendment, DecisionAmendment):
            raise ConvergentStoreError("execution amendment must satisfy the DecisionAmendment contract")
        paths = self.paths(plan_id)
        self._ensure_layout(plan_id)
        candidate = amendment.as_dict()
        with self._epoch_state_lock(paths):
            initial = self._read_state_file(paths.initial, label="execution initial")
            if initial is None:
                raise ConvergentStoreError("execution state is not initialized")
            snapshot = self._read_state_file(paths.state, label="execution state")
            events = self._read_events(paths, reject_partial=True)
            current, _snapshot_current = self._replay(initial, snapshot, events)
            assert_policy_compatible(current["policy_hash"], self.policy)
            self._validate_current_plan_provenance(current)
            if current["phase"] == "close" or current["status"] == "closed":
                raise ConvergentStoreError("execution amendments are immutable after close")
            if current["phase"] not in AMEND_ELIGIBLE_PHASES:
                raise ConvergentStoreError("material amendment cannot commit from the current phase")
            if (
                amendment.task_epoch != current.get("task_epoch")
                or amendment.prior_decision_version != current["aristotle"].get("decision_version")
                or amendment.new_decision_version != amendment.prior_decision_version + 1
                or amendment.prior_decision_fingerprint != current["aristotle"].get("decision_fingerprint")
            ):
                raise ConvergentStoreError("material amendment is not bound to the current Decision Packet version")
            try:
                result = read_jsonl(
                    paths.amendments,
                    lambda value: DecisionAmendment.from_mapping(value).as_dict(),
                    label="execution amendments",
                    total_hard_limit=MAX_STATE_BYTES,
                    max_records=self.policy.amendment_budget,
                )
            except CorruptRecordError as exc:
                raise ConvergentIntegrityError(str(exc)) from exc
            except DecisionPacketError as exc:  # pragma: no cover - wrapped by read_jsonl today
                raise ConvergentIntegrityError("execution amendment journal is invalid") from exc
            if result.partial_final_line:
                raise ConvergentIntegrityError("execution amendment journal has an incomplete final line")
            prior = next((row for row in result.records if row["amendment_id"] == amendment.amendment_id), None)
            if prior is not None:
                if prior != candidate:
                    raise ConvergentIdempotencyError("amendment ID conflicts with an earlier material payload")
                return WriteMetadata()
            if len(result.records) >= self.policy.amendment_budget:
                raise ConvergentStoreError("material amendment budget exhausted; USER_DECISION required")
            return append_jsonl(
                paths.amendments,
                candidate,
                hard_limit=MAX_EVENT_BYTES,
                total_hard_limit=MAX_STATE_BYTES,
                max_records=self.policy.amendment_budget,
                existing_records=len(result.records),
            )

    def append_amendment_approval(self, plan_id: str, approval: AmendmentApproval) -> WriteMetadata:
        """Append one content-safe Codex-main approval bound to an amendment."""

        if not isinstance(approval, AmendmentApproval):
            raise ConvergentStoreError("execution amendment approval must satisfy the typed contract")
        paths = self.paths(plan_id)
        self._ensure_layout(plan_id)
        candidate = approval.as_dict()
        with self._epoch_state_lock(paths):
            initial = self._read_state_file(paths.initial, label="execution initial")
            if initial is None:
                raise ConvergentStoreError("execution state is not initialized")
            snapshot = self._read_state_file(paths.state, label="execution state")
            events = self._read_events(paths, reject_partial=True)
            current, _snapshot_current = self._replay(initial, snapshot, events)
            self._validate_current_plan_provenance(current)
            if current["phase"] not in AMEND_ELIGIBLE_PHASES or current["status"] == "closed":
                raise ConvergentStoreError("material amendment approval cannot commit from the current phase")
            amendments = self._read_amendment_records(paths)
            amendment = next(
                (row for row in amendments if row.get("amendment_fingerprint") == approval.amendment_fingerprint),
                None,
            )
            if amendment is None:
                raise ConvergentStoreError("material amendment approval has no typed amendment")
            expected = {
                "amendment_id": amendment["amendment_id"],
                "task_epoch": amendment["task_epoch"],
                "prior_decision_version": amendment["prior_decision_version"],
                "new_decision_version": amendment["new_decision_version"],
            }
            if any(candidate.get(key) != value for key, value in expected.items()):
                raise ConvergentStoreError("material amendment approval version binding is stale")
            records = self._read_amendment_approvals(paths)
            prior = next(
                (row for row in records if row["approval_fingerprint"] == approval.approval_fingerprint),
                None,
            )
            if prior is not None:
                if prior != candidate:
                    raise ConvergentIdempotencyError("approval fingerprint conflicts with an earlier payload")
                return WriteMetadata()
            if records:
                raise ConvergentStoreError("material amendment approval budget exhausted")
            return append_jsonl(
                paths.amendment_approvals,
                candidate,
                hard_limit=MAX_EVENT_BYTES,
                total_hard_limit=MAX_STATE_BYTES,
                max_records=self.policy.amendment_budget,
                existing_records=len(records),
            )

    def _validate_plan_provenance(self, state: Mapping[str, Any], active_plan: Mapping[str, Any]) -> None:
        """Bind the task digest to the registered plan bytes before mutation."""

        raw_path = active_plan.get("plan_path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ConvergentStoreError("canonical implementation plan path is required")
        relative = Path(raw_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ConvergentStoreError("canonical implementation plan path escapes the checkout")
        candidate = self.progress.paths.primary_root / relative
        try:
            info = candidate.lstat()
            if candidate.is_symlink():
                raise ConvergentStoreError("canonical implementation plan must be a regular non-aliased file")
            target = candidate.resolve()
            target.relative_to(self.progress.paths.primary_root.resolve())
        except (OSError, ValueError) as exc:
            raise ConvergentStoreError("canonical implementation plan bytes are unavailable") from exc
        if not target.is_file() or info.st_nlink != 1:
            raise ConvergentStoreError("canonical implementation plan must be a regular non-aliased file")
        try:
            if target.stat().st_size > MAX_PLAN_BYTES:
                raise ConvergentStoreError("canonical implementation plan exceeds the bounded size")
            with target.open("rb") as handle:
                raw = handle.read(MAX_PLAN_BYTES + 1)
            if len(raw) > MAX_PLAN_BYTES:
                raise ConvergentStoreError("canonical implementation plan exceeds the bounded size")
            actual = "sha256:" + hashlib.sha256(raw).hexdigest()
        except OSError as exc:
            raise ConvergentStoreError("canonical implementation plan bytes are unavailable") from exc
        if actual != state["plan_digest"]:
            raise ConvergentStoreError("execution plan_digest does not match canonical plan bytes")

    def _validate_current_plan_provenance(self, state: Mapping[str, Any]) -> None:
        """Recheck the registered plan bytes before authority or mutation.

        The plan is an immutable input to the state machine.  Revalidating it
        after startup prevents an ignored/local plan edit from silently
        changing the design that an existing execution state claims to use.
        """

        active_plan = self.progress.read_state(str(state["plan_id"]))
        if active_plan is None:
            raise ConvergentStoreError("canonical implementation plan is unavailable")
        self._validate_plan_provenance(state, active_plan)

    def _compile_goal_artifact(self, state: Mapping[str, Any], *, active_plan: Mapping[str, Any] | None = None) -> dict[str, Any]:
        try:
            goal_id = str(state["goal_id"])
            compilation_args = {
                "plan_id": str(state["plan_id"]),
                "plan_version": int(state["plan_version"]),
                "plan_digest": str(state["plan_digest"]),
                "state_generation": int(state["generation"]),
                "active_plan": active_plan,
                "decision_packet": active_plan.get("latest_decision") if isinstance(active_plan, Mapping) else None,
                "goal_id": goal_id,
            }
            declared = compile_goals(completed=(), **compilation_args)
            known_goal_ids = tuple(goal.goal_id for goal in declared)
            goal_index = known_goal_ids.index(goal_id)
            goals = compile_goals(completed=known_goal_ids[:goal_index], **compilation_args)
        except (GoalCompileError, ValueError) as exc:
            raise ConvergentStoreError("execution state cannot compile the approved serial goal set") from exc
        return {
            "schema_version": 1,
            "plan_id": state["plan_id"],
            "plan_version": state["plan_version"],
            "plan_digest": state["plan_digest"],
            "state_generation": state["generation"],
            "goals": [goal.as_dict() for goal in goals],
        }

    def _ensure_goal_artifact(self, paths: ExecutionPaths, expected: Mapping[str, Any]) -> WriteMetadata:
        try:
            current = read_json(
                paths.goals,
                lambda value: deepcopy(dict(value)),
                label="execution goals",
                hard_limit=MAX_STATE_BYTES,
            )
        except CorruptRecordError as exc:
            raise ConvergentIntegrityError(str(exc)) from exc
        if current is not None:
            if current != expected:
                raise ConvergentIntegrityError("persisted execution goals differ from the deterministic compiler")
            return WriteMetadata()
        return publish_json(paths.goals, dict(expected), hard_limit=MAX_STATE_BYTES)

    def _ensure_layout(self, plan_id: str) -> None:
        ensure_store_layout(self.progress.paths)
        plan = self.progress.plan_paths(plan_id)
        ensure_directory_chain(plan.root, mode=0o700)
        ensure_directory_chain(self.paths(plan_id).root, mode=0o700)

    @staticmethod
    def _epoch_movable_names() -> tuple[str, ...]:
        return (
            "initial.json",
            "state.json",
            "events.jsonl",
            "goals.json",
            "aristotle-evidence.json",
            "decision-packet.json",
            "findings.json",
            "final-audit.json",
            "evidence-manifest.json",
            "handoff.json",
            "amendments.jsonl",
            "amendment-approvals.jsonl",
            "tool-results.jsonl",
            "active-epoch.json",
        )

    def _recover_pending_rotation(self, paths: ExecutionPaths) -> None:
        """Recover a rotation interrupted before active-pointer publication."""

        if not paths.rotation_pending.exists():
            return
        try:
            marker = read_json(
                paths.rotation_pending,
                lambda value: deepcopy(dict(value)),
                label="pending epoch rotation",
                hard_limit=MAX_STATE_BYTES,
            )
        except CorruptRecordError as exc:
            raise ConvergentIntegrityError(str(exc)) from exc
        required = {
            "schema_version",
            "archive_name",
            "candidate_epoch_id",
            "candidate_task_id",
            "operation_id",
            "operation_digest",
            "previous_state_hash",
            "files",
            "present_files",
        }
        if not isinstance(marker, Mapping) or set(marker) != required:
            raise ConvergentIntegrityError("pending epoch rotation marker schema is invalid")
        if marker.get("schema_version") != 1 or tuple(marker.get("files") or ()) != self._epoch_movable_names():
            raise ConvergentIntegrityError("pending epoch rotation marker is invalid")
        present_files = marker.get("present_files")
        if not isinstance(present_files, list) or any(name not in self._epoch_movable_names() for name in present_files):
            raise ConvergentIntegrityError("pending epoch rotation present-file set is invalid")
        present_set = set(present_files)
        archive_name = str(marker.get("archive_name") or "")
        if not archive_name or "/" in archive_name or "\\" in archive_name or archive_name in {".", ".."}:
            raise ConvergentIntegrityError("pending epoch rotation archive is unsafe")
        pointer = None
        if paths.active_epoch.exists():
            try:
                pointer = read_json(
                    paths.active_epoch,
                    lambda value: deepcopy(dict(value)),
                    label="execution active epoch",
                    hard_limit=MAX_STATE_BYTES,
                )
            except CorruptRecordError as exc:
                raise ConvergentIntegrityError(str(exc)) from exc
        if isinstance(pointer, Mapping) and (
            pointer.get("epoch_id") == marker.get("candidate_epoch_id")
            and pointer.get("task_id") == marker.get("candidate_task_id")
            and pointer.get("activation_operation_id") == marker.get("operation_id")
            and pointer.get("activation_operation_digest") == marker.get("operation_digest")
        ):
            os.unlink(paths.rotation_pending)
            return
        archive = paths.root / "epochs" / archive_name
        try:
            archive_info = archive.lstat()
        except OSError as exc:
            if isinstance(exc, FileNotFoundError) and self._predecessor_is_restored(paths, marker["previous_state_hash"]):
                os.unlink(paths.rotation_pending)
                return
            raise ConvergentIntegrityError("pending epoch rotation archive is missing") from exc
        if (
            stat.S_ISLNK(archive_info.st_mode)
            or not stat.S_ISDIR(archive_info.st_mode)
            or archive_info.st_mode & 0o077
        ):
            raise ConvergentIntegrityError("pending epoch rotation archive is not a private regular directory")
        try:
            archive_entries = tuple(archive.iterdir())
        except OSError as exc:
            raise ConvergentIntegrityError("pending epoch rotation archive cannot be inspected") from exc
        if any(entry.name not in self._epoch_movable_names() for entry in archive_entries):
            raise ConvergentIntegrityError("pending epoch rotation archive contains an unexpected entry")
        for entry in archive_entries:
            try:
                entry_info = entry.lstat()
            except OSError as exc:
                raise ConvergentIntegrityError("pending epoch rotation archive entry cannot be inspected") from exc
            if stat.S_ISLNK(entry_info.st_mode) or not stat.S_ISREG(entry_info.st_mode) or entry_info.st_nlink != 1 or entry_info.st_mode & 0o077:
                raise ConvergentIntegrityError("pending epoch rotation archive entry is unsafe")
        for name in self._epoch_movable_names():
            source = paths.root / name
            target = archive / name
            for path in (source, target):
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise ConvergentIntegrityError("pending epoch rotation file cannot be inspected") from exc
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077:
                    raise ConvergentIntegrityError("pending epoch rotation file is unsafe")
            if name not in present_set:
                # This file did not exist in the predecessor.  If the
                # candidate created it before the crash, it must not survive
                # when the predecessor is restored.
                if target.exists():
                    raise ConvergentIntegrityError("pending epoch rotation archive contains an unexpected file")
                if source.exists():
                    os.unlink(source)
                continue
            if source.exists() and target.exists():
                os.unlink(source)
            if not source.exists() and target.exists():
                os.replace(target, source)
            if not source.exists() and not target.exists():
                raise ConvergentIntegrityError("pending epoch rotation predecessor file is missing")
        if any((archive / name).exists() for name in self._epoch_movable_names()):
            raise ConvergentIntegrityError("pending epoch rotation archive could not be restored")
        if not self._predecessor_is_restored(paths, marker["previous_state_hash"]):
            raise ConvergentIntegrityError("pending epoch rotation predecessor is not restored")
        os.rmdir(archive)
        os.unlink(paths.rotation_pending)

    def _predecessor_is_restored(self, paths: ExecutionPaths, expected_state_hash: object) -> bool:
        if not isinstance(expected_state_hash, str) or not SHA256_RE.fullmatch(expected_state_hash):
            raise ConvergentIntegrityError("pending epoch rotation predecessor hash is invalid")
        state = self._read_state_file(paths.state, label="execution predecessor state")
        if state is None or state.get("state_hash") != expected_state_hash:
            return False
        if not paths.active_epoch.exists():
            return True
        try:
            pointer = read_json(
                paths.active_epoch,
                lambda value: deepcopy(dict(value)),
                label="execution predecessor epoch pointer",
                hard_limit=MAX_STATE_BYTES,
            )
        except CorruptRecordError as exc:
            raise ConvergentIntegrityError(str(exc)) from exc
        return isinstance(pointer, Mapping) and pointer.get("state_hash") == expected_state_hash

    @contextmanager
    def _epoch_state_lock(self, paths: ExecutionPaths):
        """Acquire locks in the one allowed epoch-then-state order."""

        with locked_file(paths.epoch_lock):
            with locked_file(paths.state_lock):
                # Recovery mutates the same namespace as every other
                # operation and therefore must run while both locks are held.
                # This prevents a reader/writer holding state.lock from
                # observing or accepting candidate files during rollback.
                self._recover_pending_rotation(paths)
                yield

    def _publish_active_epoch(
        self,
        paths: ExecutionPaths,
        state: Mapping[str, Any],
        *,
        request: TransitionRequest,
        previous_epoch_id: str = "",
    ) -> WriteMetadata:
        """Publish the active-epoch CAS marker after the state event.

        The marker is deliberately advisory for the legacy layout (where it
        is absent).  Once a rotation creates it, every authoritative read and
        mutation must validate its state hash and operation binding before
        proceeding.  Publication is last, so a crash leaves a detectable
        prepared/invalid state rather than silently selecting a different
        epoch.
        """

        payload = self._active_epoch_payload(
            state,
            operation_id=request.operation_id,
            operation_digest=request.operation_digest(),
            previous_epoch_id=previous_epoch_id,
        )
        return publish_json(paths.active_epoch, payload, hard_limit=MAX_STATE_BYTES)

    @staticmethod
    def _active_epoch_payload(
        state: Mapping[str, Any],
        *,
        operation_id: str,
        operation_digest: str,
        previous_epoch_id: str,
    ) -> dict[str, Any]:
        material = {
            "schema_version": 1,
            "plan_id": state["plan_id"],
            "plan_version": state["plan_version"],
            "plan_digest": state["plan_digest"],
            "control_generation": 2,
            "epoch_sequence": int(state["boundary_epoch"]),
            "epoch_id": str(state["task_epoch"]),
            "task_epoch_digest": digest_text(str(state["task_epoch"])),
            "task_id": str(state["task_id"]),
            "state_generation": int(state["generation"]),
            "state_hash": str(state["state_hash"]),
            "activation_operation_id": operation_id,
            "activation_operation_digest": operation_digest,
            "previous_epoch_id": previous_epoch_id,
        }
        return {**material, "pointer_digest": digest_value(material)}

    @staticmethod
    def _active_epoch_fields() -> frozenset[str]:
        return frozenset(
            {
                "schema_version",
                "plan_id",
                "plan_version",
                "plan_digest",
                "control_generation",
                "epoch_sequence",
                "epoch_id",
                "task_epoch_digest",
                "task_id",
                "state_generation",
                "state_hash",
                "activation_operation_id",
                "activation_operation_digest",
                "previous_epoch_id",
                "pointer_digest",
            }
        )

    def _read_active_epoch_pointer(self, paths: ExecutionPaths) -> Mapping[str, Any] | None:
        if not paths.active_epoch.exists():
            return None
        try:
            pointer = read_json(
                paths.active_epoch,
                lambda value: deepcopy(dict(value)),
                label="execution active epoch",
                hard_limit=MAX_STATE_BYTES,
            )
        except CorruptRecordError as exc:
            raise ConvergentIntegrityError(str(exc)) from exc
        required = self._active_epoch_fields()
        if not isinstance(pointer, Mapping) or set(pointer) != required:
            raise ConvergentIntegrityError("active epoch pointer schema is invalid")
        material = {key: pointer[key] for key in sorted(required - {"pointer_digest"})}
        if pointer.get("pointer_digest") != digest_value(material):
            raise ConvergentIntegrityError("active epoch pointer digest is invalid")
        return pointer

    def _repair_stale_active_epoch(
        self,
        paths: ExecutionPaths,
        state: Mapping[str, Any],
        events: tuple[Mapping[str, Any], ...],
    ) -> WriteMetadata:
        """Repair only a digest-valid pointer lagging a committed event."""

        pointer = self._read_active_epoch_pointer(paths)
        if pointer is None:
            return WriteMetadata()
        immutable_expected = {
            "schema_version": 1,
            "plan_id": state.get("plan_id"),
            "plan_version": state.get("plan_version"),
            "plan_digest": state.get("plan_digest"),
            "control_generation": 2,
            "epoch_sequence": int(state.get("boundary_epoch") or 0),
            "epoch_id": state.get("task_epoch"),
            "task_epoch_digest": digest_text(str(state.get("task_epoch"))),
            "task_id": state.get("task_id"),
        }
        if any(pointer.get(key) != value for key, value in immutable_expected.items()):
            raise ConvergentIntegrityError("active epoch pointer does not bind the current task epoch")
        pointer_generation = pointer.get("state_generation")
        if isinstance(pointer_generation, bool) or not isinstance(pointer_generation, int):
            raise ConvergentIntegrityError("active epoch pointer generation is invalid")
        current_generation = int(state.get("generation") or 0)
        if pointer_generation > current_generation:
            raise ConvergentIntegrityError("active epoch pointer is ahead of the journal")
        historic = next((event for event in events if event.get("generation") == pointer_generation), None)
        if historic is None or (
            pointer.get("state_hash") != historic.get("new_state_hash")
            or pointer.get("activation_operation_id") != historic.get("operation_id")
            or pointer.get("activation_operation_digest") != historic.get("operation_digest")
        ):
            raise ConvergentIntegrityError("active epoch pointer is not bound to a committed event")
        if pointer_generation == current_generation:
            return WriteMetadata()
        latest = events[-1] if events else None
        if latest is None or latest.get("generation") != current_generation or latest.get("new_state_hash") != state.get("state_hash"):
            raise ConvergentIntegrityError("active epoch pointer cannot be repaired from the journal")
        repaired = self._active_epoch_payload(
            state,
            operation_id=str(latest["operation_id"]),
            operation_digest=str(latest["operation_digest"]),
            previous_epoch_id=str(pointer.get("previous_epoch_id") or ""),
        )
        return publish_json(paths.active_epoch, repaired, hard_limit=MAX_STATE_BYTES)

    def _validate_active_epoch(self, paths: ExecutionPaths, state: Mapping[str, Any]) -> None:
        """Fail closed on a present but stale/corrupt active epoch marker."""

        pointer = self._read_active_epoch_pointer(paths)
        if pointer is None:
            return
        if (
            pointer.get("plan_id") != state.get("plan_id")
            or pointer.get("plan_version") != state.get("plan_version")
            or pointer.get("plan_digest") != state.get("plan_digest")
            or pointer.get("epoch_id") != state.get("task_epoch")
            or pointer.get("task_id") != state.get("task_id")
            or pointer.get("state_generation") != state.get("generation")
            or pointer.get("state_hash") != state.get("state_hash")
            or pointer.get("task_epoch_digest") != digest_text(str(state.get("task_epoch")))
        ):
            raise ConvergentIntegrityError("active epoch pointer does not bind the current state")

    @staticmethod
    def _tool_result_record(request: TransitionRequest) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "operation_id": request.operation_id,
            "operation_digest": request.operation_digest(),
            "task_id": request.task_id,
            "task_epoch": request.task_epoch,
            "epoch_id": request.epoch_id,
            "expected_generation": request.expected_generation,
            "tool_use_id": request.tool_use_id,
            "tool_kind": request.tool_kind,
            "head_digest": request.head_digest,
            "runtime_attestation_digest": request.runtime_attestation_digest,
            "attestation_digest": request.attestation_digest,
            "evidence_manifest_digest": request.evidence_manifest_digest,
        }

    @staticmethod
    def _read_tool_result_records(paths: ExecutionPaths) -> tuple[dict[str, Any], ...]:
        try:
            result = read_jsonl(
                paths.tool_results,
                lambda value: _validate_tool_result_record(value),
                label="execution tool results",
                total_hard_limit=MAX_JOURNAL_BYTES,
                max_records=MAX_EVENTS,
            )
        except CorruptRecordError as exc:
            raise ConvergentIntegrityError(str(exc)) from exc
        if result.partial_final_line:
            raise ConvergentIntegrityError("execution tool-result journal has an incomplete final line")
        return result.records

    def _read_state_file(self, path: Path, *, label: str) -> dict[str, Any] | None:
        try:
            return read_json(path, validate_state, label=label, hard_limit=MAX_STATE_BYTES)
        except CorruptRecordError as exc:
            raise ConvergentIntegrityError(str(exc)) from exc

    def _read_events(self, paths: ExecutionPaths, *, reject_partial: bool) -> tuple[dict[str, Any], ...]:
        try:
            result = read_jsonl(
                paths.events,
                validate_event,
                label="execution events",
                total_hard_limit=MAX_JOURNAL_BYTES,
                max_records=MAX_EVENTS,
            )
        except CorruptRecordError as exc:
            raise ConvergentIntegrityError(str(exc)) from exc
        if reject_partial and result.partial_final_line:
            raise ConvergentIntegrityError("execution journal has an incomplete final line")
        return result.records

    def _replay(
        self,
        initial: Mapping[str, Any],
        snapshot: Mapping[str, Any] | None,
        events: tuple[dict[str, Any], ...],
    ) -> tuple[dict[str, Any], bool]:
        running = validate_state(initial)
        assert_policy_compatible(running["policy_hash"], self.policy)
        states = {running["generation"]: running}
        previous_event_hash = ""
        operation_ids: dict[str, str] = {}
        for index, event in enumerate(events, start=1):
            if event["sequence"] != index:
                raise ConvergentIntegrityError("execution events are out of order")
            if event["generation"] != running["generation"] + 1:
                raise ConvergentIntegrityError("execution event generation is out of order")
            if event["previous_event_hash"] != previous_event_hash:
                raise ConvergentIntegrityError("execution event hash chain is broken")
            if event["policy_hash"] != running["policy_hash"]:
                raise ConvergentIntegrityError("execution event policy hash drifted")
            if event["previous_state_hash"] != running["state_hash"] or event["precondition_digest"] != running["state_hash"]:
                raise ConvergentIntegrityError("execution event precondition does not match replay state")
            prior = operation_ids.get(event["operation_id"])
            if prior is not None:
                raise ConvergentIntegrityError("journal contains a duplicate operation ID")
            operation_ids[event["operation_id"]] = event["operation_digest"]
            candidate = deepcopy(running)
            candidate.update(deepcopy(event["state_patch"]))
            candidate["state_hash"] = event["new_state_hash"]
            try:
                running = validate_state(candidate)
            except ContractError as exc:
                raise ConvergentIntegrityError("execution event patch cannot reconstruct valid state") from exc
            if running["state_hash"] != event["new_state_hash"]:
                raise ConvergentIntegrityError("execution event new-state hash is invalid")
            states[running["generation"]] = running
            previous_event_hash = event["event_hash"]

        if snapshot is None:
            return running, False
        normalized_snapshot = validate_state(snapshot)
        snapshot_generation = normalized_snapshot["generation"]
        expected = states.get(snapshot_generation)
        if expected is None or expected["state_hash"] != normalized_snapshot["state_hash"]:
            raise ConvergentIntegrityError("execution snapshot is ahead of or diverges from its journal")
        return running, normalized_snapshot["state_hash"] == running["state_hash"]


def _assert_safe_artifact(value: object, *, label: str = "artifact") -> None:
    if isinstance(value, Mapping):
        if len(value) > 512:
            raise ConvergentStoreError(f"{label} object exceeds its item limit")
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 180:
                raise ConvergentStoreError(f"{label} contains an invalid key")
            compact_key = re.sub(r"[^a-z0-9]+", "", key.lower())
            if key.lower() in FORBIDDEN_KEYS or compact_key in FORBIDDEN_KEY_TOKENS:
                raise ConvergentStoreError("execution artifact contains forbidden raw fields")
            _assert_safe_artifact(item, label=f"{label}.{key}")
        return
    if isinstance(value, (list, tuple)):
        if len(value) > 4096:
            raise ConvergentStoreError(f"{label} array exceeds its item limit")
        for index, item in enumerate(value):
            _assert_safe_artifact(item, label=f"{label}[{index}]")
        return
    if isinstance(value, str):
        if len(value.encode("utf-8")) > 8_192 or is_red(value):
            raise ConvergentStoreError(f"{label} is oversized or contains RED material")
        return
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float) and isfinite(value):
        return
    raise ConvergentStoreError(f"{label} contains a non-JSON value")


def _validate_tool_result_record(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CorruptRecordError("execution tool-result record is not an object")
    required = {
        "schema_version",
        "operation_id",
        "operation_digest",
        "task_id",
        "task_epoch",
        "epoch_id",
        "expected_generation",
        "tool_use_id",
        "tool_kind",
        "head_digest",
        "runtime_attestation_digest",
        "attestation_digest",
        "evidence_manifest_digest",
    }
    if set(value) != required or value.get("schema_version") != 1:
        raise CorruptRecordError("execution tool-result record schema is invalid")
    for field in (
        "operation_digest",
        "task_id",
        "head_digest",
        "runtime_attestation_digest",
        "attestation_digest",
        "evidence_manifest_digest",
    ):
        item = value.get(field)
        if not isinstance(item, str) or not SHA256_RE.fullmatch(item):
            raise CorruptRecordError(f"execution tool-result {field} is invalid")
    for field in ("operation_id", "task_epoch", "epoch_id", "tool_use_id"):
        item = value.get(field)
        if not isinstance(item, str) or not item or len(item) > 180:
            raise CorruptRecordError(f"execution tool-result {field} is invalid")
    if value.get("tool_kind") not in {"implementation_write", "validation_gate"}:
        raise CorruptRecordError("execution tool-result tool_kind is invalid")
    generation = value.get("expected_generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        raise CorruptRecordError("execution tool-result generation is invalid")
    return dict(value)


__all__ = [
    "ConvergentIdempotencyError",
    "ConvergentIntegrityError",
    "ConvergentStore",
    "ConvergentStoreError",
    "ConvergentStoreResult",
    "ExecutionPaths",
]
