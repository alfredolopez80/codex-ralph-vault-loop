"""Pure monotonic reducer for the schema-v3 convergent control state."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from .convergent_contracts import (
    ContractError,
    ExecutionLease,
    SHA256_RE,
    TRANSITIONS,
    canonical_json,
    digest_text,
    digest_value,
    state_hash,
    validate_state,
)
from .execution_policy import ExecutionPolicy, assert_policy_compatible


class TransitionError(ContractError):
    """Raised for stale, invalid, non-convergent, or budget-breaking actions."""


@dataclass(frozen=True)
class TransitionRequest:
    operation_id: str
    transition: str
    expected_generation: int
    target_phase: str = ""
    evidence_ids: tuple[str, ...] = ()
    obligation_closures: tuple[str, ...] = ()
    finding_closures: tuple[str, ...] = ()
    accepted_finding_ids: tuple[str, ...] = ()
    actor_role: str = "deterministic-runtime"
    tier: str = ""
    risk: str = "low"
    decision_fingerprint: str = ""
    amendment_fingerprint: str = ""
    evidence_manifest_digest: str = ""
    findings_digest: str = ""
    final_audit_digest: str = ""
    failure_fingerprint: str = ""
    critical: bool = False
    audit_pass: bool | None = None
    hard_gates_pass: bool | None = None
    reason: str = ""
    lease: ExecutionLease | None = None
    handoff_digest: str = ""
    recall: Mapping[str, Any] = field(default_factory=dict)

    def operation_digest(self) -> str:
        value = asdict(self)
        value["lease"] = self.lease.as_dict() if self.lease is not None else None
        value["recall"] = dict(self.recall)
        return digest_value(value)


@dataclass(frozen=True)
class Reduction:
    state: dict[str, Any]
    transition: str
    operation_digest: str
    terminal: bool = False
    user_decision_reason: str = ""


def reduce_state(state: Mapping[str, Any], request: TransitionRequest, *, policy: ExecutionPolicy) -> Reduction:
    before = validate_state(state)
    assert_policy_compatible(before["policy_hash"], policy)
    _validate_request(request)
    if request.expected_generation != before["generation"]:
        raise TransitionError("stale execution generation")
    if before["phase"] == "close" or before["status"] == "closed":
        raise TransitionError("closed tasks cannot become active")
    if before["status"] in {"blocked", "user-decision"} and request.transition != "REOPEN":
        raise TransitionError("terminal task requires an explicit reopen")

    after = deepcopy(before)
    old_phase = before["phase"]
    old_obligations = tuple(before["completion"]["open_obligations"])
    consumed_budget = False
    closed_findings = False
    advanced_evidence = False
    effective_transition = request.transition

    if request.transition == "BOUNDARY_CLASSIFIED":
        _require_phase(before, "prompt_gate")
        if request.lease is None:
            raise TransitionError("Prompt Gate requires a verified execution lease")
        lease = request.lease.as_dict()
        if lease["branch_fingerprint"] != digest_text(before["task_identity"]["branch"]):
            raise TransitionError("execution lease branch differs from task identity")
        if lease["task_epoch_fingerprint"] != digest_text(before["task_epoch"]):
            raise TransitionError("execution lease task epoch differs from control state")
        if lease["issued_generation"] != before["generation"]:
            raise TransitionError("execution lease generation differs from Prompt Gate state")
        after["execution_lease"] = lease
        after["phase"] = "analyze"
        _merge_recall(after, request.recall)
    elif request.transition == "ARISTOTLE_RECORDED":
        _require_phase(before, "analyze")
        if request.tier not in {"micro", "quick", "full", "critical"}:
            raise TransitionError("Aristotle tier is invalid")
        aristotle = after["aristotle"]
        if request.tier in {"full", "critical"} and not request.decision_fingerprint:
            raise TransitionError("Full/Critical Aristotle requires a Decision Packet fingerprint")
        if request.tier in {"full", "critical"}:
            if aristotle["full_runs"] >= policy.full_aristotle_budget:
                return _user_decision(before, request, "full-aristotle-budget-exhausted")
            aristotle["full_runs"] += 1
            consumed_budget = True
        aristotle["tier"] = request.tier
        aristotle["decision_version"] = max(1, aristotle["decision_version"])
        if request.decision_fingerprint:
            aristotle["decision_fingerprint"] = _required_digest(request.decision_fingerprint, "decision fingerprint")
        else:
            # Micro and Quick tiers do not emit a full Decision Packet, but all
            # later lifecycle phases still need immutable evidence that the
            # tiered analysis was recorded.  Freeze a content-free digest from
            # the task identity, tier, and decision version rather than making
            # every downstream gate guess which tiers are exempt.
            aristotle["decision_fingerprint"] = digest_value(
                {
                    "task_id": before["task_id"],
                    "tier": request.tier,
                    "decision_version": aristotle["decision_version"],
                }
            )
        after["phase"] = "design_ready"
    elif request.transition == "ADVANCE":
        consumed_budget, closed_findings = _advance(after, before, request)
    elif request.transition == "AMEND":
        if before["phase"] not in {
            "design_ready",
            "approved",
            "implement",
            "verify",
            "review",
            "finding_triage",
            "mitigate",
            "final_audit",
        }:
            raise TransitionError("material amendment is not allowed from this phase")
        aristotle = after["aristotle"]
        if aristotle["amendments"] >= policy.amendment_budget:
            return _user_decision(before, request, "material-amendment-budget-exhausted")
        if not request.amendment_fingerprint or not request.decision_fingerprint:
            raise TransitionError("material amendment requires amendment and new decision fingerprints")
        _required_digest(request.amendment_fingerprint, "amendment fingerprint")
        aristotle["amendments"] += 1
        aristotle["decision_version"] += 1
        aristotle["decision_fingerprint"] = _required_digest(request.decision_fingerprint, "decision fingerprint")
        after["completion"]["final_audit_digest"] = ""
        after["completion"]["invalidation_reason"] = request.reason or "material-change"
        after["phase"] = "analyze"
        after["status"] = "active"
        consumed_budget = True
    elif request.transition == "EVIDENCE_RECORDED":
        if not request.evidence_manifest_digest:
            raise TransitionError("evidence update requires a manifest digest")
        after["completion"]["evidence_manifest_digest"] = _required_digest(
            request.evidence_manifest_digest, "evidence manifest digest"
        )
        _close_obligations(after, request.obligation_closures)
        if request.handoff_digest:
            after["completion"]["handoff_digest"] = _required_digest(request.handoff_digest, "handoff digest")
            after["completion"]["handoff_published"] = True
        advanced_evidence = (
            after["completion"]["evidence_manifest_digest"]
            != before["completion"]["evidence_manifest_digest"]
            or after["completion"]["handoff_digest"] != before["completion"]["handoff_digest"]
        )
    elif request.transition == "TRANSIENT_RERUN":
        if before["phase"] not in {"verify", "final_audit"}:
            raise TransitionError("transient rerun is allowed only after verify or final audit")
        fingerprint = _required_digest(request.failure_fingerprint, "failure fingerprint")
        budget = after["failure_budget"]
        if budget["transient_reruns"] >= policy.transient_rerun_budget:
            return _user_decision(before, request, "transient-rerun-budget-exhausted")
        budget["transient_reruns"] += 1
        after["completion"]["invalidation_reason"] = request.reason or f"transient-failure:{fingerprint[7:19]}"
        consumed_budget = True
    elif request.transition == "REPAIR":
        if _repair_exhausted(after, request, policy=policy):
            return _user_decision(before, request, "repair-budget-exhausted")
        consumed_budget = _apply_repair(after, before, request, policy=policy, final_target="mitigate")
    elif request.transition == "REOPEN":
        if before["status"] not in {"blocked", "user-decision"}:
            raise TransitionError("only blocked or user-decision may be reopened")
        if request.actor_role != "codex-main":
            raise TransitionError("reopen requires Codex main authority")
        budget = after["failure_budget"]
        maximum = int(policy.section("execution")["max_task_reopens"])
        if budget["reopens"] >= maximum:
            return _user_decision(before, request, "task-reopen-budget-exhausted")
        budget["reopens"] += 1
        after["phase"] = "prompt_gate"
        after["status"] = "active"
        after["completion"]["terminal_reason"] = ""
        after["completion"]["invalidation_reason"] = ""
        if request.lease is not None:
            after["execution_lease"] = request.lease.as_dict()
        consumed_budget = True
    elif request.transition == "REVIEW_RECORDED":
        _require_phase(before, "review")
        if request.risk not in {"material", "critical"}:
            raise TransitionError("low-risk work has zero generative review budget")
        review = after["review"]
        if review["passes"] >= policy.review_budget_material:
            return _user_decision(before, request, "review-budget-exhausted")
        if not request.findings_digest:
            raise TransitionError("review requires a bounded findings ledger digest")
        review["passes"] += 1
        review["findings_digest"] = _required_digest(request.findings_digest, "findings digest")
        review["accepted_findings"] = _unique_ids(request.accepted_finding_ids, "accepted findings")
        after["phase"] = "finding_triage"
        consumed_budget = True
    elif request.transition == "FINDINGS_TRIAGED":
        _require_phase(before, "finding_triage")
        if not request.findings_digest:
            raise TransitionError("finding triage requires a ledger digest")
        after["review"]["findings_digest"] = _required_digest(request.findings_digest, "findings digest")
        after["review"]["accepted_findings"] = _unique_ids(request.accepted_finding_ids, "accepted findings")
        after["phase"] = "mitigate" if request.accepted_finding_ids else "final_audit"
        closed_findings = not request.accepted_finding_ids
    elif request.transition == "FINAL_AUDIT_RECORDED":
        _require_phase(before, "final_audit")
        if not request.final_audit_digest or request.audit_pass is None or request.hard_gates_pass is None:
            raise TransitionError("final audit requires digest, verdict, and hard-gate result")
        after["completion"]["final_audit_digest"] = _required_digest(request.final_audit_digest, "final audit digest")
        after["completion"]["hard_gates_pass"] = request.hard_gates_pass
        if request.audit_pass and request.hard_gates_pass:
            after["phase"] = "anti_rationalization"
            after["status"] = "verifying"
        elif request.audit_pass:
            after["phase"] = "blocked"
            after["status"] = "blocked"
            after["completion"]["terminal_reason"] = "hard-gates-failed"
        else:
            if _repair_exhausted(after, request, policy=policy):
                return _user_decision(before, request, "final-audit-repair-budget-exhausted")
            consumed_budget = _apply_repair(after, before, request, policy=policy, final_target="mitigate")
    elif request.transition == "STOP_CONTINUATION":
        _require_phase(before, "stop")
        budgets = after["stop_budget"]
        counter = "critical_continuations" if request.critical else "ordinary_continuations"
        maximum = policy.critical_stop_budget if request.critical else policy.ordinary_stop_budget
        if budgets[counter] >= maximum:
            return _user_decision(before, request, "stop-continuation-budget-exhausted")
        budgets[counter] += 1
        after["phase"] = "anti_rationalization"
        after["status"] = "verifying"
        after["completion"]["invalidation_reason"] = request.reason or (
            "critical-stop-evidence" if request.critical else "stop-evidence"
        )
        consumed_budget = True
    elif request.transition == "BLOCK":
        after["phase"] = "blocked"
        after["status"] = "blocked"
        after["completion"]["terminal_reason"] = request.reason or "blocked"
    elif request.transition == "USER_DECISION":
        after["phase"] = "user_decision"
        after["status"] = "user-decision"
        after["completion"]["terminal_reason"] = request.reason or "user-decision-required"
    elif request.transition == "CLOSE":
        _require_phase(before, "stop")
        completion = before["completion"]
        if completion["open_obligations"] or before["review"]["accepted_findings"]:
            raise TransitionError("cannot close with open obligations or accepted findings")
        if not (
            completion["hard_gates_pass"]
            and completion["evidence_manifest_digest"]
            and completion["final_audit_digest"]
            and completion["handoff_published"]
            and before["aristotle"]["decision_fingerprint"]
        ):
            raise TransitionError("deterministic close evidence is incomplete")
        after["phase"] = "close"
        after["status"] = "closed"
        after["completion"]["terminal_reason"] = request.reason or "verified-complete"
    else:  # pragma: no cover
        raise TransitionError("unsupported execution transition")

    if request.transition not in {"BOUNDARY_CLASSIFIED", "BLOCK", "USER_DECISION", "REOPEN"}:
        _require_active_lease(after)
    if request.obligation_closures and request.transition != "EVIDENCE_RECORDED":
        _close_obligations(after, request.obligation_closures)

    progressed = after["phase"] != old_phase
    reduced = len(after["completion"]["open_obligations"]) < len(old_obligations)
    terminal = after["phase"] in {"close", "blocked", "user_decision"}
    if not (progressed or reduced or advanced_evidence or consumed_budget or closed_findings or terminal):
        raise TransitionError("transition does not converge")
    return _finish(before, after, request, effective_transition, terminal=terminal)


def _advance(after: dict[str, Any], before: Mapping[str, Any], request: TransitionRequest) -> tuple[bool, bool]:
    current = before["phase"]
    consumed = False
    closed_findings = False
    if current == "design_ready":
        if not after["aristotle"]["decision_fingerprint"]:
            raise TransitionError("approval requires a frozen Decision Packet")
        target = "approved"
    elif current == "approved":
        target = "implement"
    elif current == "implement":
        target = "verify"
        after["status"] = "verifying"
    elif current == "verify":
        material = request.risk in {"material", "critical"}
        after["review"]["required"] = material
        target = "review" if material else "finding_triage"
    elif current == "mitigate":
        accepted = tuple(after["review"]["accepted_findings"])
        if not accepted:
            raise TransitionError("mitigation requires accepted findings")
        if set(request.finding_closures) != set(accepted):
            raise TransitionError("one mitigation batch must close every accepted finding")
        if after["review"]["mitigation_batches"] >= 1:
            raise TransitionError("mitigation batch budget exhausted")
        after["review"]["accepted_findings"] = []
        after["review"]["mitigation_batches"] += 1
        target = "final_audit"
        consumed = True
        closed_findings = True
    elif current == "anti_rationalization":
        target = "stop"
    else:
        raise TransitionError(f"ADVANCE is not valid from {current}")
    if request.target_phase and request.target_phase != target:
        raise TransitionError("target phase differs from deterministic lifecycle")
    after["phase"] = target
    return consumed, closed_findings


def _apply_repair(
    after: dict[str, Any],
    before: Mapping[str, Any],
    request: TransitionRequest,
    *,
    policy: ExecutionPolicy,
    final_target: str,
) -> bool:
    if before["phase"] not in {"verify", "final_audit"}:
        raise TransitionError("repair is allowed only after verify or final audit")
    fingerprint = _required_digest(request.failure_fingerprint, "failure fingerprint")
    budget = after["failure_budget"]
    used = budget["fingerprints"].get(fingerprint, 0)
    if used >= policy.repair_per_fingerprint or budget["code_repair_cycles"] >= policy.total_repair_budget:
        raise TransitionError("repair budget precondition was not normalized to USER_DECISION")
    budget["fingerprints"][fingerprint] = used + 1
    budget["code_repair_cycles"] += 1
    after["phase"] = "implement" if before["phase"] == "verify" else final_target
    after["status"] = "active"
    after["completion"]["invalidation_reason"] = request.reason or "deterministic-regression"
    after["completion"]["final_audit_digest"] = ""
    return True


def _repair_exhausted(state: Mapping[str, Any], request: TransitionRequest, *, policy: ExecutionPolicy) -> bool:
    fingerprint = _required_digest(request.failure_fingerprint, "failure fingerprint")
    budget = state["failure_budget"]
    return (
        budget["fingerprints"].get(fingerprint, 0) >= policy.repair_per_fingerprint
        or budget["code_repair_cycles"] >= policy.total_repair_budget
    )


def _user_decision(before: Mapping[str, Any], request: TransitionRequest, reason: str) -> Reduction:
    after = deepcopy(dict(before))
    after["phase"] = "user_decision"
    after["status"] = "user-decision"
    after["completion"]["terminal_reason"] = reason
    return _finish(before, after, request, "USER_DECISION", terminal=True, user_decision_reason=reason)


def _finish(
    before: Mapping[str, Any],
    after: dict[str, Any],
    request: TransitionRequest,
    transition: str,
    *,
    terminal: bool,
    user_decision_reason: str = "",
) -> Reduction:
    _sync_completion_mirrors(after)
    after["previous_state_hash"] = before["state_hash"]
    after["generation"] = before["generation"] + 1
    after["state_hash"] = ""
    after["state_hash"] = state_hash(after)
    return Reduction(
        state=validate_state(after),
        transition=transition,
        operation_digest=request.operation_digest(),
        terminal=terminal,
        user_decision_reason=user_decision_reason,
    )


def _sync_completion_mirrors(state: dict[str, Any]) -> None:
    completion = state["completion"]
    state["invalidation_reason"] = completion["invalidation_reason"]
    state["terminal_reason"] = completion["terminal_reason"]
    state["final_audit_digest"] = completion["final_audit_digest"]


def _merge_recall(state: dict[str, Any], update: Mapping[str, Any]) -> None:
    if not update:
        return
    allowed = {
        "memory_generation",
        "checkpoint_generation",
        "selection_fingerprint",
        "selected_ids",
        "delta_emitted",
        "context_epoch",
    }
    if set(update) - allowed:
        raise TransitionError("recall update has unknown fields")
    state["recall"].update(dict(update))


def _close_obligations(state: dict[str, Any], closures: tuple[str, ...]) -> None:
    if not closures:
        return
    current = list(state["completion"]["open_obligations"])
    unknown = sorted(set(closures) - set(current))
    if unknown:
        raise TransitionError("cannot close unknown obligations")
    state["completion"]["open_obligations"] = [item for item in current if item not in set(closures)]


def _require_phase(state: Mapping[str, Any], phase: str) -> None:
    if state["phase"] != phase:
        raise TransitionError(f"transition requires {phase}, found {state['phase']}")


def _require_active_lease(state: Mapping[str, Any]) -> None:
    lease = state.get("execution_lease")
    if not isinstance(lease, Mapping) or lease.get("active") is not True:
        raise TransitionError("active SOL/max execution lease is required")


def _validate_request(request: TransitionRequest) -> None:
    if request.transition not in TRANSITIONS:
        raise TransitionError("unsupported execution transition")
    if request.expected_generation < 0:
        raise TransitionError("expected generation must be nonnegative")
    if len(canonical_json(asdict(request)).encode("utf-8")) > 64 * 1024:
        raise TransitionError("transition request exceeds its byte limit")


def _required_digest(value: str, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise TransitionError(f"{label} must be a sha256 digest")
    return value


def _unique_ids(values: tuple[str, ...], label: str) -> list[str]:
    if len(values) > 64 or len(set(values)) != len(values):
        raise TransitionError(f"{label} must be bounded and unique")
    if any(not value or len(value) > 180 for value in values):
        raise TransitionError(f"{label} contains an invalid identifier")
    return list(values)


__all__ = ["Reduction", "TransitionError", "TransitionRequest", "reduce_state"]
