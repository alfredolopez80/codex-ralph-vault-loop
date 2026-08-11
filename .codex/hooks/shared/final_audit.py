"""Deterministic final-audit contract for Convergent Execution v4."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .convergent_contracts import digest_value


class FinalAuditError(ValueError):
    """Raised when a final-audit request is incomplete or unsafe."""


@dataclass(frozen=True)
class AuditGate:
    gate_id: str
    executed: bool
    passed: bool
    blocking: bool = True
    evidence_digest: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "executed": self.executed,
            "passed": self.passed,
            "blocking": self.blocking,
            "evidence_digest": self.evidence_digest,
        }


@dataclass(frozen=True)
class FinalAuditResult:
    passed: bool
    digest: str
    failed_gates: tuple[str, ...]
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "digest": self.digest, "failed_gates": list(self.failed_gates), "reason": self.reason}


# Deterministic audit keys are intentionally explicit.  They are the only
# accepted input to the compatibility runner below; missing evidence cannot
# silently become a pass.
AUDIT_CHECKS = (
    "packet_valid",
    "plan_digest_match",
    "policy_hash_match",
    "amendment_valid",
    "finding_ledger_valid",
    "accepted_findings_closed",
    "gates_complete",
    "scope_valid",
    "security_preserved",
    "branch_correct",
    "head_correct",
    "worktree_correct",
    "no_blockers",
    "notes_valid",
    "approvals_valid",
    "no_open_p0_p1",
    "evidence_manifest_valid",
)


def deterministic_final_audit(
    *,
    packet_fingerprint: str,
    plan_digest: str,
    policy_hash: str,
    evidence_manifest_digest: str,
    gates: Sequence[AuditGate],
    accepted_findings: Sequence[str] = (),
    closed_findings: Sequence[str] = (),
    p0_p1_open: bool = False,
    scope_clean: bool = True,
    security_preserved: bool = True,
    branch_correct: bool = True,
    head_correct: bool = True,
    worktree_correct: bool = True,
    no_blockers: bool = True,
    notes_valid: bool = True,
    approvals_valid: bool = True,
    plan_digest_match: bool = True,
    policy_hash_match: bool = True,
    amendment_valid: bool = True,
    finding_ledger_valid: bool = True,
) -> FinalAuditResult:
    for label, value in (("packet_fingerprint", packet_fingerprint), ("plan_digest", plan_digest), ("policy_hash", policy_hash), ("evidence_manifest_digest", evidence_manifest_digest)):
        _digest(value, label)
    for label, value in (
        ("p0_p1_open", p0_p1_open),
        ("scope_clean", scope_clean),
        ("security_preserved", security_preserved),
        ("branch_correct", branch_correct),
        ("head_correct", head_correct),
        ("worktree_correct", worktree_correct),
        ("no_blockers", no_blockers),
        ("notes_valid", notes_valid),
        ("approvals_valid", approvals_valid),
        ("plan_digest_match", plan_digest_match),
        ("policy_hash_match", policy_hash_match),
        ("amendment_valid", amendment_valid),
        ("finding_ledger_valid", finding_ledger_valid),
    ):
        if not isinstance(value, bool):
            raise FinalAuditError(f"{label} must be boolean")
    if not isinstance(gates, (list, tuple)) or any(not isinstance(gate, AuditGate) for gate in gates):
        raise FinalAuditError("audit gates must be structured AuditGate values")
    if len(gates) > 256 or len({gate.gate_id for gate in gates}) != len(gates):
        raise FinalAuditError("audit gates are unbounded or duplicate")
    failed: list[str] = []
    for gate in gates:
        if not isinstance(gate.gate_id, str) or not gate.gate_id or len(gate.gate_id) > 180:
            raise FinalAuditError("audit gate ID is invalid")
        if not isinstance(gate.executed, bool) or not isinstance(gate.passed, bool) or not isinstance(gate.blocking, bool):
            raise FinalAuditError("audit gate booleans are invalid")
        if gate.blocking and (not gate.executed or not gate.passed):
            failed.append(gate.gate_id)
    accepted = _identifiers(accepted_findings, "accepted_findings")
    closed = _identifiers(closed_findings, "closed_findings")
    accepted_findings_closed = not (set(accepted) - set(closed))
    if not accepted_findings_closed:
        failed.append("accepted_findings_closed")
    checks = {
        "packet_valid": bool(packet_fingerprint),
        "plan_digest_match": plan_digest_match,
        "policy_hash_match": policy_hash_match,
        "amendment_valid": amendment_valid,
        "finding_ledger_valid": finding_ledger_valid,
        "accepted_findings_closed": accepted_findings_closed,
        "gates_complete": bool(gates) and all(gate.executed for gate in gates),
        "scope_valid": scope_clean,
        "security_preserved": security_preserved,
        "branch_correct": branch_correct,
        "head_correct": head_correct,
        "worktree_correct": worktree_correct,
        "no_blockers": no_blockers,
        "notes_valid": notes_valid,
        "approvals_valid": approvals_valid,
        "no_open_p0_p1": not p0_p1_open,
        "evidence_manifest_valid": bool(evidence_manifest_digest),
    }
    failed.extend(name for name in AUDIT_CHECKS if not checks[name])
    failed_tuple = tuple(dict.fromkeys(failed))
    payload = {
        "packet_fingerprint": packet_fingerprint,
        "plan_digest": plan_digest,
        "policy_hash": policy_hash,
        "evidence_manifest_digest": evidence_manifest_digest,
        "gates": [gate.as_dict() for gate in gates],
        "accepted_findings": list(accepted),
        "closed_findings": list(closed),
        "checks": checks,
        "p0_p1_open": p0_p1_open,
        "failed": list(failed_tuple),
    }
    return FinalAuditResult(not failed_tuple, digest_value(payload), failed_tuple, "pass" if not failed_tuple else "blocking_gate_failed")


def validate_generative_audit_request(*, critical: bool, approved: bool, mode: str = "deterministic") -> None:
    if mode not in {"deterministic", "generative"}:
        raise FinalAuditError("audit mode is invalid")
    if mode == "generative" and (not critical or not approved):
        raise FinalAuditError("critical generative final audit requires explicit approval")


def run_final_audit(evidence: Mapping[str, Mapping[str, object]]) -> "CompatibilityAuditResult":
    """Validate the content-free check map used by the final-audit hook."""

    if set(evidence) != set(AUDIT_CHECKS):
        raise FinalAuditError("final audit check mismatch")
    failed: list[str] = []
    normalized: dict[str, object] = {}
    for check in AUDIT_CHECKS:
        value = evidence[check]
        if not isinstance(value, Mapping) or not isinstance(value.get("passed"), bool):
            raise FinalAuditError(f"final audit evidence for {check} is invalid")
        ids = value.get("evidence_ids", ())
        if not isinstance(ids, (list, tuple)) or not ids or any(not isinstance(item, str) or not item for item in ids):
            raise FinalAuditError(f"final audit evidence IDs for {check} are invalid")
        normalized[check] = {"passed": value["passed"], "evidence_ids": list(ids)}
        if not value["passed"]:
            failed.append(check)
    payload = {"mode": "deterministic", "checks": normalized, "failed": failed}
    return CompatibilityAuditResult(not failed, "deterministic", digest_value(payload), tuple(failed))


@dataclass(frozen=True)
class CompatibilityAuditResult:
    passed: bool
    mode: str
    audit_digest: str
    failed_checks: tuple[str, ...]


@dataclass(frozen=True)
class GenerativeAuditAuthorization:
    allowed: bool
    terminal: bool
    reason: str


def authorize_critical_generative_audit(*, risk: str, explicitly_approved: bool, prior_attempts: int) -> GenerativeAuditAuthorization:
    if risk not in {"low", "material", "critical"}:
        raise FinalAuditError("audit risk is invalid")
    if risk != "critical":
        return GenerativeAuditAuthorization(False, False, "critical-only")
    if not explicitly_approved:
        return GenerativeAuditAuthorization(False, False, "explicit-approval-required")
    if prior_attempts >= 1:
        return GenerativeAuditAuthorization(False, False, "terminal-audit-budget-exhausted")
    return GenerativeAuditAuthorization(True, True, "approved-terminal-audit")


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        raise FinalAuditError(f"{label} must be a sha256 digest")
    return value


def _identifiers(values: Sequence[str], label: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)) or len(values) > 128:
        raise FinalAuditError(f"{label} is unbounded")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value or len(value) > 180 or any(char.isspace() for char in value):
            raise FinalAuditError(f"{label} contains an invalid identifier")
        if value not in normalized:
            normalized.append(value)
    return tuple(normalized)


__all__ = [
    "AUDIT_CHECKS",
    "AuditGate",
    "CompatibilityAuditResult",
    "FinalAuditError",
    "FinalAuditResult",
    "GenerativeAuditAuthorization",
    "authorize_critical_generative_audit",
    "deterministic_final_audit",
    "run_final_audit",
    "validate_generative_audit_request",
]
