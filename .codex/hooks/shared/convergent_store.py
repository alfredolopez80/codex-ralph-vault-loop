"""Crash-replayable v4 control state inside the implementation store.

This is an ``execution/`` namespace below the existing canonical plan root,
not a second human-facing progress surface.  It reuses the implementation
store's no-follow locks, bounded readers, append/fsync journal, and atomic
snapshot publication.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
import re
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
)
from .convergent_reducer import Reduction, TransitionRequest, reduce_state
from .decision_packet import DecisionAmendment, DecisionPacketError
from .execution_policy import ExecutionPolicy, assert_policy_compatible
from .goal_compiler import GOAL_IDS, PLAN_ID, GoalCompileError, compile_goals
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
    findings: Path
    final_audit: Path
    amendments: Path


@dataclass(frozen=True)
class ConvergentStoreResult:
    changed: bool
    state: Mapping[str, Any] | None = None
    event: Mapping[str, Any] | None = None
    metadata: WriteMetadata = WriteMetadata()
    reason: str = ""
    replayed: bool = False


class ConvergentStore:
    def __init__(self, progress: ImplementationStore, policy: ExecutionPolicy) -> None:
        self.progress = progress
        self.policy = policy

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
            findings=root / "findings.json",
            final_audit=root / "final-audit.json",
            amendments=root / "amendments.jsonl",
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
        goals = self._compile_goal_artifact(candidate, active_plan=active_plan)
        paths = self.paths(plan_id)
        self._ensure_layout(plan_id)
        with locked_file(paths.state_lock):
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

    def read_current(self, plan_id: str) -> ConvergentStoreResult:
        paths = self.paths(plan_id)
        initial = self._read_state_file(paths.initial, label="execution initial")
        snapshot = self._read_state_file(paths.state, label="execution state")
        if initial is None:
            if snapshot is not None or paths.events.exists():
                raise ConvergentIntegrityError("execution state lacks immutable initial evidence")
            return ConvergentStoreResult(False, reason="execution state missing")
        events = self._read_events(paths, reject_partial=False)
        replayed, snapshot_current = self._replay(initial, snapshot, events)
        return ConvergentStoreResult(False, replayed, reason="read-only replay", replayed=not snapshot_current)

    def transition(self, plan_id: str, request: TransitionRequest) -> ConvergentStoreResult:
        paths = self.paths(plan_id)
        self._ensure_layout(plan_id)
        with locked_file(paths.state_lock):
            initial = self._read_state_file(paths.initial, label="execution initial")
            if initial is None:
                raise ConvergentStoreError("execution state is not initialized")
            snapshot = self._read_state_file(paths.state, label="execution state")
            events = self._read_events(paths, reject_partial=True)
            current, snapshot_current = self._replay(initial, snapshot, events)
            assert_policy_compatible(current["policy_hash"], self.policy)
            operation_digest = request.operation_digest()
            previous_operation = next((event for event in events if event["operation_id"] == request.operation_id), None)
            if previous_operation is not None:
                if previous_operation["operation_digest"] != operation_digest:
                    raise ConvergentIdempotencyError("operation ID conflicts with an earlier material payload")
                metadata = WriteMetadata()
                if not snapshot_current:
                    metadata = publish_json(paths.state, current, hard_limit=MAX_STATE_BYTES)
                return ConvergentStoreResult(
                    False,
                    current,
                    previous_operation,
                    metadata=metadata,
                    reason="idempotent retry",
                    replayed=not snapshot_current,
                )

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
            metadata = append_jsonl(
                paths.events,
                event,
                hard_limit=MAX_EVENT_BYTES,
                total_hard_limit=MAX_JOURNAL_BYTES,
                max_records=MAX_EVENTS,
                existing_records=len(events),
            )
            # Journal first: a crash before this snapshot publication is
            # recoverable from immutable initial state plus validated patches.
            metadata = metadata.plus(publish_json(paths.state, reduction.state, hard_limit=MAX_STATE_BYTES))
            return ConvergentStoreResult(True, reduction.state, event, metadata=metadata, reason="transition committed")

    def replay(self, plan_id: str) -> ConvergentStoreResult:
        paths = self.paths(plan_id)
        self._ensure_layout(plan_id)
        with locked_file(paths.state_lock):
            initial = self._read_state_file(paths.initial, label="execution initial")
            if initial is None:
                return ConvergentStoreResult(False, reason="execution state missing")
            snapshot = self._read_state_file(paths.state, label="execution state")
            events = self._read_events(paths, reject_partial=True)
            current, snapshot_current = self._replay(initial, snapshot, events)
            if snapshot_current:
                return ConvergentStoreResult(False, current, reason="already current")
            metadata = publish_json(paths.state, current, hard_limit=MAX_STATE_BYTES)
            return ConvergentStoreResult(True, current, metadata=metadata, reason="journal replayed", replayed=True)

    def publish_artifact(self, plan_id: str, name: str, payload: Mapping[str, Any]) -> WriteMetadata:
        """Publish one bounded content-safe machine artifact in execution/."""

        paths = self.paths(plan_id)
        # goals.json has a single owner: the deterministic compiler in start().
        allowed = {"findings": paths.findings, "final-audit": paths.final_audit}
        if name not in allowed:
            raise ConvergentStoreError("unsupported execution artifact")
        self._ensure_layout(plan_id)
        encoded = deepcopy(dict(payload))
        _assert_safe_artifact(encoded)
        with locked_file(paths.state_lock):
            initial = self._read_state_file(paths.initial, label="execution initial")
            if initial is None:
                raise ConvergentStoreError("execution state is not initialized")
            snapshot = self._read_state_file(paths.state, label="execution state")
            events = self._read_events(paths, reject_partial=True)
            current, _snapshot_current = self._replay(initial, snapshot, events)
            if current["phase"] == "close" or current["status"] == "closed":
                raise ConvergentStoreError("execution artifacts are immutable after close")
            return publish_json(allowed[name], encoded, hard_limit=MAX_STATE_BYTES)

    def append_amendment(self, plan_id: str, amendment: DecisionAmendment) -> WriteMetadata:
        """Append the single budgeted material amendment with ID idempotency."""

        if not isinstance(amendment, DecisionAmendment):
            raise ConvergentStoreError("execution amendment must satisfy the DecisionAmendment contract")
        paths = self.paths(plan_id)
        self._ensure_layout(plan_id)
        candidate = amendment.as_dict()
        with locked_file(paths.state_lock):
            initial = self._read_state_file(paths.initial, label="execution initial")
            if initial is None:
                raise ConvergentStoreError("execution state is not initialized")
            snapshot = self._read_state_file(paths.state, label="execution state")
            events = self._read_events(paths, reject_partial=True)
            current, _snapshot_current = self._replay(initial, snapshot, events)
            assert_policy_compatible(current["policy_hash"], self.policy)
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

    def _compile_goal_artifact(self, state: Mapping[str, Any], *, active_plan: Mapping[str, Any] | None = None) -> dict[str, Any]:
        try:
            goal_id = str(state["goal_id"])
            known_goal_ids = GOAL_IDS if state["plan_id"] == PLAN_ID else (goal_id,)
            goal_index = known_goal_ids.index(goal_id)
            goals = compile_goals(
                plan_id=str(state["plan_id"]),
                plan_version=int(state["plan_version"]),
                plan_digest=str(state["plan_digest"]),
                state_generation=int(state["generation"]),
                completed=known_goal_ids[:goal_index],
                active_plan=active_plan,
                decision_packet=active_plan.get("latest_decision") if isinstance(active_plan, Mapping) else None,
                goal_id=goal_id,
            )
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


__all__ = [
    "ConvergentIdempotencyError",
    "ConvergentIntegrityError",
    "ConvergentStore",
    "ConvergentStoreError",
    "ConvergentStoreResult",
    "ExecutionPaths",
]
