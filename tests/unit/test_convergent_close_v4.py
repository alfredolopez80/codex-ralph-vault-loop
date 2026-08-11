from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.convergent_contracts import TaskIdentity, digest_text, new_state  # noqa: E402
from shared.convergent_reducer import TransitionRequest, reduce_state  # noqa: E402
from shared.convergent_stop import (  # noqa: E402
    evaluate_anti_rationalization,
    plan_stop_attempt,
    terminal_attempt_fingerprint,
)
from shared.execution_lease import LeaseEvidence, acquire_execution_lease  # noqa: E402
from shared.execution_policy import PolicyDriftError, load_execution_policy  # noqa: E402
from shared.goal_compiler import PLAN_DIGEST, PLAN_ID  # noqa: E402


def _initial() -> dict:
    policy = load_execution_policy()
    identity = TaskIdentity.from_values(
        session="session-close",
        project="project-close",
        worktree="workspace-close",
        branch="codex/ralph-convergent-execution-v4",
        objective="Verify deterministic close",
        boundary_epoch=1,
        sensitivity="GREEN",
        plan=PLAN_ID,
        plan_version=1,
        plan_digest=PLAN_DIGEST,
    )
    return new_state(
        policy=policy,
        plan_id=PLAN_ID,
        plan_version=1,
        plan_digest=PLAN_DIGEST,
        task_identity=identity,
        goal_id="G-EVIDENCE-CLOSE",
        task_epoch="epoch-close",
        boundary_epoch=1,
        boundary_kind="new_task",
        activation_mode="shadow",
    )


def _request(state: dict, operation: str, transition: str, **changes: object) -> TransitionRequest:
    values: dict[str, object] = {
        "operation_id": operation,
        "transition": transition,
        "expected_generation": state["generation"],
    }
    values.update(changes)
    return TransitionRequest(**values)  # type: ignore[arg-type]


def _stop_state(*, complete: bool) -> dict:
    policy = load_execution_policy()
    state = _initial()
    lease = acquire_execution_lease(
        LeaseEvidence(
            model="gpt-5.6-sol",
            reasoning_effort="max",
            tools=("apply_patch", "exec_command"),
            cwd=str(ROOT),
            branch="codex/ralph-convergent-execution-v4",
            task_epoch="epoch-close",
            owner_role="sol-worker",
            authority_role="codex-main",
            source="verified-runtime",
        ),
        policy=policy,
        issued_generation=0,
    )
    state = reduce_state(
        state, _request(state, "op-boundary-close", "BOUNDARY_CLASSIFIED", lease=lease), policy=policy
    ).state
    state = reduce_state(
        state,
        _request(
            state,
            "op-design-close",
            "ARISTOTLE_RECORDED",
            tier="full",
            decision_fingerprint=digest_text("close-packet"),
        ),
        policy=policy,
    ).state
    for operation in ("op-approve-close", "op-implement-close", "op-verify-close", "op-triage-close"):
        state = reduce_state(state, _request(state, operation, "ADVANCE"), policy=policy).state
    state = reduce_state(
        state,
        _request(state, "op-findings-close", "FINDINGS_TRIAGED", findings_digest=digest_text("none")),
        policy=policy,
    ).state
    if complete:
        state = reduce_state(
            state,
            _request(
                state,
                "op-evidence-close",
                "EVIDENCE_RECORDED",
                evidence_manifest_digest=digest_text("manifest"),
                handoff_digest=digest_text("handoff"),
            ),
            policy=policy,
        ).state
    state = reduce_state(
        state,
        _request(
            state,
            "op-audit-close",
            "FINAL_AUDIT_RECORDED",
            final_audit_digest=digest_text("audit"),
            audit_pass=True,
            hard_gates_pass=True,
        ),
        policy=policy,
    ).state
    return reduce_state(state, _request(state, "op-stop-phase", "ADVANCE"), policy=policy).state


def test_anti_rationalization_uses_objective_evidence_and_phrases_are_signal_only() -> None:
    complete = _stop_state(complete=True)
    verdict = evaluate_anti_rationalization(
        complete,
        stage="stop",
        assistant_text="This is probably done, with a later follow-up.",
    )
    assert verdict.passed is True
    assert verdict.action == "advance"
    assert set(verdict.phrase_signals) == {"completion-claim", "deferral-claim", "uncertainty-claim"}

    incomplete = _stop_state(complete=False)
    verdict = evaluate_anti_rationalization(incomplete, stage="stop", assistant_text="No completion claim here.")
    assert verdict.passed is False
    assert set(verdict.evidence_failures) == {"evidence-manifest", "handoff"}

    no_evidence = evaluate_anti_rationalization(_initial(), stage="phase_exit", assistant_text="done")
    assert no_evidence.passed is False
    assert "hard-gates" in no_evidence.evidence_failures
    assert no_evidence.phrase_signals == ("completion-claim",)


def test_stop_close_duplicate_and_ordinary_budget_are_finite() -> None:
    policy = load_execution_policy()
    complete = _stop_state(complete=True)
    attempt = terminal_attempt_fingerprint(complete)
    assert plan_stop_attempt(complete, policy=policy, attempt_fingerprint=attempt).transition == "CLOSE"
    duplicate = plan_stop_attempt(
        complete,
        policy=policy,
        attempt_fingerprint=attempt,
        previous_terminal_fingerprint=attempt,
    )
    assert duplicate.physical_no_op is True

    incomplete = _stop_state(complete=False)
    decision = plan_stop_attempt(
        incomplete,
        policy=policy,
        attempt_fingerprint=terminal_attempt_fingerprint(incomplete),
    )
    assert decision.transition == "STOP_CONTINUATION"
    incomplete = reduce_state(
        incomplete,
        _request(incomplete, "op-ordinary-continuation", "STOP_CONTINUATION", reason="missing-evidence"),
        policy=policy,
    ).state
    incomplete = reduce_state(incomplete, _request(incomplete, "op-ordinary-return-stop", "ADVANCE"), policy=policy).state
    exhausted = plan_stop_attempt(
        incomplete,
        policy=policy,
        attempt_fingerprint=terminal_attempt_fingerprint(incomplete),
    )
    assert exhausted.transition == "USER_DECISION"


def test_distinct_critical_stop_budget_is_independent_and_finite() -> None:
    policy = load_execution_policy()
    state = _stop_state(complete=False)
    assert plan_stop_attempt(
        state,
        policy=policy,
        attempt_fingerprint=terminal_attempt_fingerprint(state),
        critical=True,
    ).transition == "STOP_CONTINUATION"
    state = reduce_state(
        state,
        _request(
            state,
            "op-critical-continuation",
            "STOP_CONTINUATION",
            critical=True,
            reason="distinct-critical-evidence",
        ),
        policy=policy,
    ).state
    assert state["stop_budget"] == {"ordinary_continuations": 0, "critical_continuations": 1}
    state = reduce_state(state, _request(state, "op-critical-return-stop", "ADVANCE"), policy=policy).state
    exhausted = plan_stop_attempt(
        state,
        policy=policy,
        attempt_fingerprint=terminal_attempt_fingerprint(state),
        critical=True,
    )
    assert exhausted.transition == "USER_DECISION"


def test_stop_planning_blocks_active_policy_hash_drift() -> None:
    state = _stop_state(complete=True)
    drifted = replace(load_execution_policy(), policy_hash=digest_text("drifted-policy"))
    with pytest.raises(PolicyDriftError):
        plan_stop_attempt(
            state,
            policy=drifted,
            attempt_fingerprint=terminal_attempt_fingerprint(state),
        )
