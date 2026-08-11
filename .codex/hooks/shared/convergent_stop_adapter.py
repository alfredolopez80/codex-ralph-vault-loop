"""Bounded adapter from the Stop hook payload to the v4 Stop contract.

The legacy Stop reducer remains the compatibility path until repo-local v4
enforcement is approved.  A v4 state snapshot is therefore opt-in: shadow
mode evaluates it without changing hook output, while enforce mode emits only
the supported bounded block response for an incomplete or invalid snapshot.
No snapshot, prompt, or phrase text is persisted by this adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .convergent_contracts import ContractError, FutureExecutionSchemaError
from .convergent_stop import StopContractError, evaluate_anti_rationalization, plan_stop_attempt, terminal_attempt_fingerprint
from .execution_policy import ExecutionPolicy, ExecutionPolicyError, load_execution_policy


@dataclass(frozen=True)
class ConvergentStopAdapterResult:
    action: str
    reason: str
    physical_no_op: bool = False
    evidence_digest: str = ""
    transition: str = ""
    expected_generation: int = -1


def evaluate_convergent_stop(
    payload: Mapping[str, object],
    *,
    policy: ExecutionPolicy | None = None,
    trusted_previous_terminal_fingerprint: str = "",
) -> ConvergentStopAdapterResult | None:
    """Evaluate an explicitly supplied v4 state snapshot.

    ``None`` means that the payload belongs to the legacy reducer (there is no
    v4 snapshot).  This keeps off/shadow compatibility deterministic while
    ensuring enforce mode never treats a malformed v4 snapshot as success.
    """

    candidate = payload.get("convergence_state")
    if candidate is None:
        return None
    if not isinstance(candidate, Mapping):
        return ConvergentStopAdapterResult("block", "convergent-state-invalid")
    try:
        active_policy = policy or load_execution_policy()
        anti = evaluate_anti_rationalization(
            candidate,
            stage="stop",
            assistant_text=str(payload.get("last_assistant_message") or "")[:8_000],
        )
        # Attempt identity is derived from the validated snapshot.  Payload
        # fields are untrusted and cannot manufacture a duplicate terminal
        # result.  The optional prior fingerprint is accepted only from the
        # lock-held persisted terminal marker in the Stop dispatcher.
        attempt_fingerprint = terminal_attempt_fingerprint(candidate)
        previous_fingerprint = trusted_previous_terminal_fingerprint if isinstance(trusted_previous_terminal_fingerprint, str) else ""
        decision = plan_stop_attempt(
            candidate,
            policy=active_policy,
            attempt_fingerprint=attempt_fingerprint,
            previous_terminal_fingerprint=previous_fingerprint,
            critical=str(candidate.get("risk") or "") == "critical",
        )
    except (ContractError, FutureExecutionSchemaError, StopContractError, ExecutionPolicyError, TypeError, ValueError):
        return ConvergentStopAdapterResult("block", "convergent-state-invalid")

    if decision.physical_no_op:
        return ConvergentStopAdapterResult(
            "physical-no-op",
            "duplicate-terminal-attempt",
            physical_no_op=True,
            evidence_digest=anti.evidence_digest,
            expected_generation=int(candidate["generation"]),
        )
    if decision.action == "close" and anti.passed:
        return ConvergentStopAdapterResult(
            "allow",
            "objective-evidence-complete",
            evidence_digest=anti.evidence_digest,
            transition="CLOSE",
            expected_generation=int(candidate["generation"]),
        )
    if decision.action == "user-decision":
        return ConvergentStopAdapterResult(
            "block",
            "stop-continuation-budget-exhausted",
            evidence_digest=anti.evidence_digest,
            transition="USER_DECISION",
            expected_generation=int(candidate["generation"]),
        )
    return ConvergentStopAdapterResult(
        "block",
        "objective-evidence-incomplete",
        evidence_digest=anti.evidence_digest,
        transition="STOP_CONTINUATION",
        expected_generation=int(candidate["generation"]),
    )


__all__ = ["ConvergentStopAdapterResult", "evaluate_convergent_stop"]
