from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.convergent_contracts import ContractError, TaskIdentity, digest_text, new_state, state_hash, validate_state  # noqa: E402
from shared.convergent_reducer import TransitionError, TransitionRequest, reduce_state  # noqa: E402
from shared.execution_lease import (  # noqa: E402
    DelegationEvidence,
    LeaseError,
    LeaseEvidence,
    acquire_execution_lease,
    assert_lease_stable,
    evidence_from_payload,
    validate_delegation_evidence,
)
from shared.execution_policy import load_execution_policy  # noqa: E402
from shared.goal_compiler import PLAN_ID  # noqa: E402


PLAN_DIGEST = "sha256:fead6e85227c68c863fa23ccccc30f559c3893ced514704f5643c61d1c41b5e1"


def identity() -> TaskIdentity:
    return TaskIdentity.from_values(
        session="session-1",
        project="project-1",
        worktree="workspace-1",
        branch="codex/ralph-convergent-execution-v4",
        objective="Implement convergent execution",
        boundary_epoch=1,
        sensitivity="GREEN",
        plan=PLAN_ID,
        plan_version=1,
        plan_digest=PLAN_DIGEST,
    )


def initial(*, obligations: tuple[str, ...] = ()) -> dict:
    return new_state(
        policy=load_execution_policy(),
        plan_id=PLAN_ID,
        plan_version=1,
        plan_digest=PLAN_DIGEST,
        task_identity=identity(),
        goal_id="G-DECISION",
        task_epoch="epoch-1",
        boundary_epoch=1,
        boundary_kind="new_task",
        activation_mode="shadow",
        obligations=obligations,
    )


def lease_evidence(**changes: object) -> LeaseEvidence:
    values: dict[str, object] = {
        "model": "gpt-5.6-sol",
        "reasoning_effort": "max",
        "tools": ("apply_patch", "exec_command"),
        "cwd": str(ROOT),
        "branch": "codex/ralph-convergent-execution-v4",
        "task_epoch": "epoch-1",
        "owner_role": "sol-worker",
        "authority_role": "codex-main",
        "source": "verified-runtime",
    }
    values.update(changes)
    return LeaseEvidence(**values)  # type: ignore[arg-type]


def request(state: dict, operation: str, transition: str, **changes: object) -> TransitionRequest:
    values: dict[str, object] = {
        "operation_id": operation,
        "transition": transition,
        "expected_generation": state["generation"],
    }
    values.update(changes)
    return TransitionRequest(**values)  # type: ignore[arg-type]


def activate(state: dict) -> dict:
    policy = load_execution_policy()
    lease = acquire_execution_lease(lease_evidence(), policy=policy, issued_generation=state["generation"])
    return reduce_state(state, request(state, "op-boundary", "BOUNDARY_CLASSIFIED", lease=lease), policy=policy).state


def design_ready(state: dict) -> dict:
    policy = load_execution_policy()
    state = activate(state)
    return reduce_state(
        state,
        request(
            state,
            "op-aristotle",
            "ARISTOTLE_RECORDED",
            tier="full",
            decision_fingerprint=digest_text("packet-v1"),
        ),
        policy=policy,
    ).state


def verified_candidate(state: dict, *, risk: str = "low") -> dict:
    policy = load_execution_policy()
    state = design_ready(state)
    for operation in ("op-approved", "op-implement", "op-verify", "op-candidate"):
        state = reduce_state(state, request(state, operation, "ADVANCE", risk=risk), policy=policy).state
    return state


def test_sol_max_lease_rejects_fallback_alternate_models_and_drift() -> None:
    policy = load_execution_policy()
    lease = acquire_execution_lease(lease_evidence(), policy=policy, issued_generation=0)
    assert lease.model == "gpt-5.6-sol"
    assert lease.effort == "max"
    assert lease.implementation_owner == "sol-worker"

    for changes in (
        {"model": "gpt-5.6-luna"},
        {"model": "gpt-5.6-terra"},
        {"reasoning_effort": "high"},
        {"owner_role": "sol-advisor"},
        {"fallback_requested": True},
        {"source": "payload"},
    ):
        with pytest.raises(LeaseError):
            acquire_execution_lease(lease_evidence(**changes), policy=policy, issued_generation=0)

    with pytest.raises(LeaseError, match="generation"):
        acquire_execution_lease(lease_evidence(), policy=policy, issued_generation=-1)

    with pytest.raises(LeaseError, match="toolset"):
        assert_lease_stable(lease.as_dict(), lease_evidence(tools=("exec_command",)), policy=policy)

    for changes, message in (
        ({"branch": "codex/another-branch"}, "branch"),
        ({"task_epoch": "epoch-other"}, "task epoch"),
    ):
        mismatched = acquire_execution_lease(
            lease_evidence(**changes),
            policy=policy,
            issued_generation=0,
        )
        state = initial()
        with pytest.raises(TransitionError, match=message):
            reduce_state(
                state,
                request(state, f"op-mismatched-{message.replace(' ', '-')}", "BOUNDARY_CLASSIFIED", lease=mismatched),
                policy=policy,
            )

    future_generation = acquire_execution_lease(lease_evidence(), policy=policy, issued_generation=1)
    state = initial()
    with pytest.raises(TransitionError, match="generation"):
        reduce_state(
            state,
            request(state, "op-mismatched-generation", "BOUNDARY_CLASSIFIED", lease=future_generation),
            policy=policy,
        )


def test_payload_cannot_self_attest_platform_identity_source() -> None:
    policy = load_execution_policy()
    payload = {
        "runtime": {
            "model": "gpt-5.6-sol",
            "reasoning_effort": "max",
            "cwd": str(ROOT),
            "branch": "codex/ralph-convergent-execution-v4",
            "tools": ["apply_patch", "exec_command"],
            "model_source": "platform",
        }
    }
    unverified = evidence_from_payload(payload, task_epoch="epoch-1")
    assert unverified.source == "payload"
    with pytest.raises(LeaseError, match="runtime-verifiable"):
        acquire_execution_lease(unverified, policy=policy, issued_generation=0)

    verified = evidence_from_payload(payload, task_epoch="epoch-1", verified_source="platform")
    assert verified.tools == ("apply_patch", "exec_command")
    assert acquire_execution_lease(verified, policy=policy, issued_generation=0).model == "gpt-5.6-sol"


def test_delegation_is_manual_finite_independent_and_non_overlapping() -> None:
    policy = load_execution_policy()
    valid = DelegationEvidence(
        automatic=False,
        active_children=0,
        total_threads=1,
        depth=1,
        nested=False,
        independent_block=True,
        measurable_success=True,
        non_overlapping_write_scope=True,
    )
    validate_delegation_evidence(valid, policy=policy)
    for changes in (
        {"automatic": True},
        {"active_children": 1},
        {"total_threads": 2},
        {"total_threads": 0},
        {"depth": 2},
        {"depth": 0},
        {"nested": True},
        {"independent_block": False},
        {"measurable_success": False},
        {"non_overlapping_write_scope": False},
    ):
        values = {**valid.__dict__, **changes}
        with pytest.raises(LeaseError):
            validate_delegation_evidence(DelegationEvidence(**values), policy=policy)


def test_state_uses_schema_three_nested_contract_and_strict_guards() -> None:
    state = initial(obligations=("gate-1",))
    assert state["schema_version"] == 3
    assert set(state) >= {
        "task_id",
        "boundary_epoch",
        "boundary_kind",
        "execution_lease",
        "aristotle",
        "guards",
        "recall",
        "review",
        "failure_budget",
        "stop_budget",
        "invalidation_reason",
        "terminal_reason",
        "final_audit_digest",
        "completion",
    }
    assert validate_state(state) == state
    identity = state["task_identity"]
    assert identity["session_id"].startswith("sha256:")
    assert identity["project_id"].startswith("sha256:")
    assert identity["worktree_id"].startswith("sha256:")
    assert identity["branch"] == "codex/ralph-convergent-execution-v4"
    assert identity["boundary_epoch"] == 1
    assert identity["sensitivity"] == "GREEN"
    assert identity["plan_id"] == PLAN_ID
    assert identity["plan_version"] == 1
    assert identity["plan_digest"] == PLAN_DIGEST

    weakened = dict(state)
    weakened["guards"] = {**state["guards"], "red_egress": "sometimes"}
    with pytest.raises(ValueError, match="cannot be weakened"):
        validate_state(weakened)

    mismatched = dict(state)
    mismatched["terminal_reason"] = "unexpected"
    mismatched["state_hash"] = ""
    mismatched["state_hash"] = state_hash(mismatched)
    with pytest.raises(ContractError, match="must mirror"):
        validate_state(mismatched)

    over_budget = initial()
    over_budget["failure_budget"]["transient_reruns"] = 2
    over_budget["state_hash"] = ""
    over_budget["state_hash"] = state_hash(over_budget)
    with pytest.raises(ContractError, match="transient rerun state exceeds"):
        validate_state(over_budget)

    inconsistent_repairs = initial()
    inconsistent_repairs["failure_budget"]["code_repair_cycles"] = 1
    inconsistent_repairs["state_hash"] = ""
    inconsistent_repairs["state_hash"] = state_hash(inconsistent_repairs)
    with pytest.raises(ContractError, match="repair counters"):
        validate_state(inconsistent_repairs)


def test_normal_low_risk_lifecycle_is_monotonic_and_closes_deterministically() -> None:
    policy = load_execution_policy()
    state = verified_candidate(initial(obligations=("gate-1",)), risk="low")
    assert state["phase"] == "finding_triage"
    assert state["review"]["passes"] == 0

    state = reduce_state(
        state,
        request(state, "op-triage", "FINDINGS_TRIAGED", findings_digest=digest_text("no-findings")),
        policy=policy,
    ).state
    assert state["phase"] == "final_audit"
    state = reduce_state(
        state,
        request(
            state,
            "op-evidence",
            "EVIDENCE_RECORDED",
            evidence_manifest_digest=digest_text("manifest"),
            obligation_closures=("gate-1",),
            handoff_digest=digest_text("handoff"),
        ),
        policy=policy,
    ).state
    state = reduce_state(
        state,
        request(
            state,
            "op-audit",
            "FINAL_AUDIT_RECORDED",
            final_audit_digest=digest_text("audit"),
            audit_pass=True,
            hard_gates_pass=True,
        ),
        policy=policy,
    ).state
    state = reduce_state(state, request(state, "op-stop", "ADVANCE"), policy=policy).state
    state = reduce_state(state, request(state, "op-close", "CLOSE"), policy=policy).state

    assert state["phase"] == "close"
    assert state["status"] == "closed"
    assert state["completion"]["hard_gates_pass"] is True
    assert state["final_audit_digest"] == state["completion"]["final_audit_digest"]
    assert state["terminal_reason"] == "verified-complete"
    assert state["invalidation_reason"] == state["completion"]["invalidation_reason"]
    with pytest.raises(TransitionError, match="closed tasks"):
        reduce_state(state, request(state, "op-restart", "REOPEN", actor_role="codex-main"), policy=policy)


def test_material_review_runs_once_and_mitigation_is_one_batch() -> None:
    policy = load_execution_policy()
    state = verified_candidate(initial(), risk="material")
    assert state["phase"] == "review"
    state = reduce_state(
        state,
        request(
            state,
            "op-review",
            "REVIEW_RECORDED",
            risk="material",
            findings_digest=digest_text("findings-v1"),
            accepted_finding_ids=("F-1", "F-2"),
        ),
        policy=policy,
    ).state
    state = reduce_state(
        state,
        request(
            state,
            "op-triage-material",
            "FINDINGS_TRIAGED",
            findings_digest=digest_text("triaged-v1"),
            accepted_finding_ids=("F-1", "F-2"),
        ),
        policy=policy,
    ).state
    assert state["phase"] == "mitigate"
    with pytest.raises(TransitionError, match="every accepted"):
        reduce_state(
            state,
            request(state, "op-partial-mitigation", "ADVANCE", finding_closures=("F-1",)),
            policy=policy,
        )
    state = reduce_state(
        state,
        request(state, "op-mitigation", "ADVANCE", finding_closures=("F-1", "F-2")),
        policy=policy,
    ).state
    assert state["phase"] == "final_audit"
    assert state["review"]["passes"] == 1
    assert state["review"]["mitigation_batches"] == 1
    assert state["review"]["accepted_findings"] == []


def test_stale_generation_blocks_and_repair_exhaustion_becomes_user_decision() -> None:
    policy = load_execution_policy()
    state = design_ready(initial())
    for operation in ("op-approved-repair", "op-implement-repair", "op-verify-repair"):
        state = reduce_state(state, request(state, operation, "ADVANCE"), policy=policy).state
    assert state["phase"] == "verify"
    with pytest.raises(TransitionError, match="stale"):
        reduce_state(
            state,
            TransitionRequest(operation_id="op-stale", transition="REPAIR", expected_generation=0),
            policy=policy,
        )

    fingerprint = digest_text("same deterministic failure")
    state = reduce_state(
        state,
        request(state, "op-repair-1", "REPAIR", failure_fingerprint=fingerprint),
        policy=policy,
    ).state
    state = reduce_state(state, request(state, "op-back-to-verify", "ADVANCE"), policy=policy).state
    exhausted = reduce_state(
        state,
        request(state, "op-repair-2", "REPAIR", failure_fingerprint=fingerprint),
        policy=policy,
    )
    assert exhausted.state["phase"] == "user_decision"
    assert exhausted.user_decision_reason == "repair-budget-exhausted"


def test_transient_rerun_and_material_amendment_exhaustion_require_user_decision() -> None:
    policy = load_execution_policy()
    state = design_ready(initial())
    for operation in ("op-approved-budget", "op-implement-budget", "op-verify-budget"):
        state = reduce_state(state, request(state, operation, "ADVANCE"), policy=policy).state
    fingerprint = digest_text("transient deterministic failure")
    first_rerun = reduce_state(
        state,
        request(state, "op-transient-1", "TRANSIENT_RERUN", failure_fingerprint=fingerprint),
        policy=policy,
    )
    assert first_rerun.state["phase"] == "verify"
    assert first_rerun.state["failure_budget"]["transient_reruns"] == 1
    exhausted_rerun = reduce_state(
        first_rerun.state,
        request(first_rerun.state, "op-transient-2", "TRANSIENT_RERUN", failure_fingerprint=fingerprint),
        policy=policy,
    )
    assert exhausted_rerun.state["phase"] == "user_decision"
    assert exhausted_rerun.user_decision_reason == "transient-rerun-budget-exhausted"

    state = design_ready(initial())
    state = reduce_state(
        state,
        request(
            state,
            "op-amend-1",
            "AMEND",
            amendment_fingerprint=digest_text("amendment-v1"),
            decision_fingerprint=digest_text("packet-v2"),
            reason="new-material-evidence",
        ),
        policy=policy,
    ).state
    state = reduce_state(
        state,
        request(
            state,
            "op-amended-analysis",
            "ARISTOTLE_RECORDED",
            tier="quick",
            decision_fingerprint=digest_text("packet-v2"),
        ),
        policy=policy,
    ).state
    exhausted_amendment = reduce_state(
        state,
        request(
            state,
            "op-amend-2",
            "AMEND",
            amendment_fingerprint=digest_text("amendment-v2"),
            decision_fingerprint=digest_text("packet-v3"),
        ),
        policy=policy,
    )
    assert exhausted_amendment.state["phase"] == "user_decision"
    assert exhausted_amendment.user_decision_reason == "material-amendment-budget-exhausted"


def test_reopen_budget_is_preserved_and_exhaustion_stays_user_decision() -> None:
    policy = load_execution_policy()
    state = activate(initial())
    state = reduce_state(state, request(state, "op-block-1", "BLOCK", reason="first-block"), policy=policy).state
    state = reduce_state(
        state,
        request(state, "op-reopen-1", "REOPEN", actor_role="codex-main"),
        policy=policy,
    ).state
    assert state["failure_budget"]["reopens"] == 1
    state = reduce_state(state, request(state, "op-block-2", "BLOCK", reason="second-block"), policy=policy).state
    exhausted = reduce_state(
        state,
        request(state, "op-reopen-2", "REOPEN", actor_role="codex-main"),
        policy=policy,
    )
    assert exhausted.state["phase"] == "user_decision"
    assert exhausted.state["failure_budget"]["reopens"] == 1
    assert exhausted.user_decision_reason == "task-reopen-budget-exhausted"
