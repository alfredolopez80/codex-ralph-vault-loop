from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".codex" / "hooks"))

from shared.final_audit import AUDIT_CHECKS, AuditGate, FinalAuditError, deterministic_final_audit, run_final_audit, validate_generative_audit_request  # noqa: E402


def digest(seed: str) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(seed.encode()).hexdigest()


def gates(*, passed: bool = True) -> list[AuditGate]:
    return [AuditGate(name, True, passed, True, digest(name)) for name in ("tests", "lint", "security")]


def test_deterministic_audit_requires_all_gates_and_closes_findings() -> None:
    result = deterministic_final_audit(
        packet_fingerprint=digest("packet"),
        plan_digest=digest("plan"),
        policy_hash=digest("policy"),
        evidence_manifest_digest=digest("manifest"),
        gates=gates(),
        accepted_findings=["F-1"],
        closed_findings=["F-1"],
    )
    assert result.passed is True
    assert result.digest.startswith("sha256:")

    failed = deterministic_final_audit(
        packet_fingerprint=digest("packet"),
        plan_digest=digest("plan"),
        policy_hash=digest("policy"),
        evidence_manifest_digest=digest("manifest"),
        gates=gates(passed=False),
        accepted_findings=["F-1"],
        closed_findings=[],
    )
    assert failed.passed is False
    assert "accepted_findings_closed" in failed.failed_gates


def test_deterministic_audit_rejects_non_hex_sha256_values() -> None:
    with pytest.raises(FinalAuditError, match="sha256 digest"):
        deterministic_final_audit(
            packet_fingerprint="sha256:" + "z" * 64,
            plan_digest=digest("plan"),
            policy_hash=digest("policy"),
            evidence_manifest_digest=digest("manifest"),
            gates=gates(),
        )


def test_critical_generative_audit_requires_explicit_approval() -> None:
    with pytest.raises(FinalAuditError, match="approval"):
        validate_generative_audit_request(critical=True, approved=False, mode="generative")
    validate_generative_audit_request(critical=True, approved=True, mode="generative")
    with pytest.raises(FinalAuditError, match="critical"):
        validate_generative_audit_request(critical=False, approved=True, mode="generative")
    with pytest.raises(FinalAuditError, match="mode"):
        validate_generative_audit_request(critical=False, approved=False, mode="other")


def test_deterministic_audit_keeps_head_blockers_and_hash_identity_explicit() -> None:
    result = deterministic_final_audit(
        packet_fingerprint=digest("packet"),
        plan_digest=digest("plan"),
        policy_hash=digest("policy"),
        evidence_manifest_digest=digest("manifest"),
        gates=gates(),
        head_correct=False,
        no_blockers=False,
        plan_digest_match=False,
        policy_hash_match=False,
        amendment_valid=False,
        finding_ledger_valid=False,
    )
    assert result.passed is False
    assert {"head_correct", "no_blockers", "plan_digest_match", "policy_hash_match", "amendment_valid", "finding_ledger_valid"} <= set(result.failed_gates)


def test_compatibility_audit_requires_evidence_for_every_explicit_check() -> None:
    evidence = {check: {"passed": True, "evidence_ids": [f"EV-{index}"]} for index, check in enumerate(AUDIT_CHECKS)}
    result = run_final_audit(evidence)
    assert result.passed is True
    evidence["head_correct"]["evidence_ids"] = []
    with pytest.raises(FinalAuditError, match="evidence IDs"):
        run_final_audit(evidence)
