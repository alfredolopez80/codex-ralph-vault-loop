"""Crash-replayable v4 control state inside the implementation store.

This is an ``execution/`` namespace below the existing canonical plan root,
not a second human-facing progress surface.  It reuses the implementation
store's no-follow locks, bounded readers, append/fsync journal, and atomic
snapshot publication.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
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
    digest_value,
    SHA256_RE,
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
    decision_packet: Path
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
            decision_packet=root / "decision-packet.json",
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
        self._validate_plan_provenance(candidate, active_plan)
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

    def read_current(self, plan_id: str, *, authoritative: bool = False) -> ConvergentStoreResult:
        paths = self.paths(plan_id)
        initial = self._read_state_file(paths.initial, label="execution initial")
        snapshot = self._read_state_file(paths.state, label="execution state")
        if initial is None:
            if snapshot is not None or paths.events.exists():
                raise ConvergentIntegrityError("execution state lacks immutable initial evidence")
            return ConvergentStoreResult(False, reason="execution state missing")
        events = self._read_events(paths, reject_partial=authoritative)
        replayed, snapshot_current = self._replay(initial, snapshot, events)
        self._validate_current_plan_provenance(replayed)
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
            self._validate_current_plan_provenance(current)
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

            # Idempotent retries are answered from the journal before checking
            # mutable artifacts.  A later, legitimate packet/triage artifact
            # replacement must not make the already-committed operation look
            # invalid; only a genuinely new operation is bound to the current
            # artifact generation.
            self._validate_transition_artifacts(paths, current, request)

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
            self._require_packet_digest(paths.decision_packet, request.decision_fingerprint, current=current)
        elif request.transition == "ARISTOTLE_RECORDED":
            if request.decision_fingerprint:
                self._require_packet_digest(paths.decision_packet, request.decision_fingerprint, current=current)
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
        elif request.transition == "FINAL_AUDIT_RECORDED":
            audit = self._read_final_audit(paths.final_audit, current=current)
            if audit.audit_digest != request.final_audit_digest:
                raise ConvergentStoreError("final audit artifact digest is not bound to the transition")
            if request.audit_pass is not audit.passed:
                raise ConvergentStoreError("final audit verdict does not match the typed audit artifact")
            if request.hard_gates_pass is not audit.passed:
                raise ConvergentStoreError("final audit hard-gate verdict does not match the typed audit artifact")
            self._require_decision_evidence(paths, current)
            if current["review"].get("findings_digest"):
                ledger = self._read_finding_ledger(paths.findings)
                if ledger.findings_digest != current["review"]["findings_digest"]:
                    raise ConvergentStoreError("final audit findings ledger is stale")

    @staticmethod
    def _read_final_audit(path: Path, *, current: Mapping[str, Any] | None = None):
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
                accepted = tuple(sorted(payload.get("accepted_finding_ids", [])))
                closed = tuple(sorted(payload.get("closed_finding_ids", [])))
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

    @staticmethod
    def _require_packet_digest(path: Path, expected: str, *, current: Mapping[str, Any] | None = None) -> None:
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

    @staticmethod
    def _require_decision_evidence(paths: ExecutionPaths, current: Mapping[str, Any]) -> None:
        """Validate either a typed packet or the deterministic low-risk record."""

        aristotle = current.get("aristotle") if isinstance(current.get("aristotle"), Mapping) else {}
        tier = str(aristotle.get("tier") or "")
        expected = str(aristotle.get("decision_fingerprint") or "")
        if tier in {"full", "critical"}:
            ConvergentStore._require_packet_digest(paths.decision_packet, expected, current=current)
            return
        synthetic = digest_value(
            {
                "task_id": current.get("task_id"),
                "tier": tier,
                "decision_version": aristotle.get("decision_version"),
            }
        )
        if tier not in {"micro", "quick"} or expected != synthetic:
            raise ConvergentStoreError("low-risk Aristotle evidence is missing or invalid")

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
        allowed = {
            "decision-packet": paths.decision_packet,
            "findings": paths.findings,
            "final-audit": paths.final_audit,
        }
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
                    and row.get("new_decision_fingerprint")
                    for row in amendments
                )
                if not pending_amendment:
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
        with locked_file(paths.state_lock):
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
