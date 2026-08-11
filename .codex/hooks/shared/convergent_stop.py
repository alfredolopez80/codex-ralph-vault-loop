"""Evidence-authoritative Anti-Rationalization and finite Stop decisions."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .convergent_contracts import SHA256_RE, digest_value, validate_state
from .execution_policy import ExecutionPolicy, assert_policy_compatible


CLAIM_SIGNALS = (
    ("completion-claim", re.compile(r"\b(done|complete|completed|finished|listo|terminado|completado)\b", re.I)),
    ("deferral-claim", re.compile(r"\b(later|follow[- ]?up|future work|despu[eé]s|pendiente)\b", re.I)),
    ("uncertainty-claim", re.compile(r"\b(probably|should be|seems|creo que|parece)\b", re.I)),
)


class StopContractError(ValueError):
    """Raised when a Stop decision is requested outside the finite contract."""


@dataclass(frozen=True)
class AntiRationalizationDecision:
    passed: bool
    action: str
    evidence_failures: tuple[str, ...]
    phrase_signals: tuple[str, ...]
    evidence_digest: str


@dataclass(frozen=True)
class StopDecision:
    action: str
    transition: str
    reason: str
    physical_no_op: bool


def evaluate_anti_rationalization(
    state: Mapping[str, Any],
    *,
    stage: str,
    assistant_text: str = "",
) -> AntiRationalizationDecision:
    if stage not in {"phase_exit", "stop"}:
        raise StopContractError("Anti-Rationalization runs only on phase exit or Stop")
    normalized = validate_state(state)
    failures = _completion_failures(normalized)
    signals = tuple(code for code, pattern in CLAIM_SIGNALS if pattern.search(assistant_text[:8_000]))
    material = {
        "state_hash": normalized["state_hash"],
        "stage": stage,
        "evidence_failures": list(failures),
        # Phrase text is signal-only and never enters persistent evidence.
        "phrase_signals": list(signals),
    }
    return AntiRationalizationDecision(
        passed=not failures,
        action="advance" if not failures else "block",
        evidence_failures=failures,
        phrase_signals=signals,
        evidence_digest=digest_value(material),
    )


def plan_stop_attempt(
    state: Mapping[str, Any],
    *,
    policy: ExecutionPolicy,
    attempt_fingerprint: str,
    previous_terminal_fingerprint: str = "",
    critical: bool = False,
) -> StopDecision:
    normalized = validate_state(state)
    assert_policy_compatible(normalized["policy_hash"], policy)
    fingerprint = _digest(attempt_fingerprint, "attempt_fingerprint")
    if normalized["phase"] == "close":
        # A closed snapshot is terminal.  It may only be acknowledged when a
        # trusted persisted marker proves that this exact attempt was already
        # committed; caller-provided fingerprints are never sufficient.
        if previous_terminal_fingerprint:
            prior = _digest(previous_terminal_fingerprint, "previous_terminal_fingerprint")
            if prior == fingerprint:
                return StopDecision("physical-no-op", "", "duplicate-terminal-attempt", True)
        raise StopContractError("a closed task accepts only an identified duplicate terminal attempt")
    if normalized["phase"] != "stop":
        raise StopContractError("Stop planning requires the stop phase")
    failures = _completion_failures(normalized)
    # Duplicate suppression is deliberately after completion validation.  A
    # malicious caller must not turn an incomplete state into a terminal
    # physical no-op by supplying the same arbitrary value twice.
    if not failures and previous_terminal_fingerprint:
        prior = _digest(previous_terminal_fingerprint, "previous_terminal_fingerprint")
        if prior == fingerprint:
            return StopDecision("physical-no-op", "", "duplicate-terminal-attempt", True)
    if not failures:
        return StopDecision("close", "CLOSE", "objective-evidence-complete", False)
    counter = "critical_continuations" if critical else "ordinary_continuations"
    maximum = policy.critical_stop_budget if critical else policy.ordinary_stop_budget
    if normalized["stop_budget"][counter] >= maximum:
        return StopDecision("user-decision", "USER_DECISION", "stop-continuation-budget-exhausted", False)
    return StopDecision("continue", "STOP_CONTINUATION", "objective-evidence-incomplete", False)


def terminal_attempt_fingerprint(state: Mapping[str, Any]) -> str:
    normalized = validate_state(state)
    return digest_value(
        {
            "task_id": normalized["task_id"],
            "task_epoch": normalized["task_epoch"],
            "state_hash": normalized["state_hash"],
            "final_audit_digest": normalized["completion"]["final_audit_digest"],
            "evidence_manifest_digest": normalized["completion"]["evidence_manifest_digest"],
        }
    )


def _completion_failures(state: Mapping[str, Any]) -> tuple[str, ...]:
    completion = state["completion"]
    failures: list[str] = []
    if not completion["hard_gates_pass"]:
        failures.append("hard-gates")
    if completion["open_obligations"]:
        failures.append("open-obligations")
    if state["review"]["accepted_findings"]:
        failures.append("accepted-findings")
    if not completion["evidence_manifest_digest"]:
        failures.append("evidence-manifest")
    if not completion["final_audit_digest"]:
        failures.append("final-audit")
    if not completion["handoff_published"] or not completion["handoff_digest"]:
        failures.append("handoff")
    if not state["aristotle"]["decision_fingerprint"]:
        failures.append("decision-packet")
    lease = state.get("execution_lease")
    if not isinstance(lease, Mapping) or lease.get("active") is not True:
        failures.append("execution-lease")
    return tuple(failures)


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise StopContractError(f"{label} must be a sha256 digest")
    return value


__all__ = [
    "AntiRationalizationDecision",
    "StopContractError",
    "StopDecision",
    "evaluate_anti_rationalization",
    "plan_stop_attempt",
    "terminal_attempt_fingerprint",
]
