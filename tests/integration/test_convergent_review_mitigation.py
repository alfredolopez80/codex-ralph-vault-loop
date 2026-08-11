from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".codex" / "hooks"))

from shared.convergent_review import Finding, FindingLedger, ReviewContractError, ReviewLedger, triage_findings  # noqa: E402


def finding(identifier: str, root: str, status: str = "ACCEPT") -> Finding:
    return Finding.create(
        finding_id=identifier,
        severity="P1",
        location="module.py:10",
        root_cause=root,
        impact="The contract could be violated.",
        evidence=[f"EV-{identifier}"],
        recommended_fix="Apply the bounded repair.",
        status=status,
    )


def test_material_review_is_one_pass_and_accepted_findings_batch_by_root_cause() -> None:
    ledger = ReviewLedger.create(risk="material", findings=[finding("F-1", "root-a"), finding("F-2", "root-a"), finding("F-3", "root-b", "PRE_EXISTING")])
    assert ledger.accepted()[0].finding_id == "F-1"
    assert ledger.mitigation_batches() == (("root-a", ("F-1", "F-2")),)
    triaged = triage_findings(ledger.findings)
    assert triaged["ACCEPT"] == ("F-1", "F-2")
    assert triaged["PRE_EXISTING"] == ("F-3",)


def test_low_risk_and_second_review_are_blocked() -> None:
    with pytest.raises(ReviewContractError, match="low-risk"):
        ReviewLedger.create(risk="low", findings=[])
    first = ReviewLedger.create(risk="critical", findings=[finding("F-1", "root")])
    with pytest.raises(ReviewContractError, match="exhausted"):
        ReviewLedger.create(risk="critical", findings=[], prior_passes=first.pass_number)


def test_compatibility_finding_ledger_rejects_low_risk_review_pass() -> None:
    with pytest.raises(ReviewContractError, match="zero automatic review"):
        FindingLedger.create(risk="low", review_pass=1, review_owner="reviewer", findings=[])


def test_review_ledger_rejects_unstructured_or_evidence_free_findings() -> None:
    with pytest.raises(ReviewContractError, match="structured"):
        ReviewLedger.create(risk="material", findings=["F-raw"])  # type: ignore[list-item]
    with pytest.raises(ReviewContractError, match="at least one"):
        Finding.create(
            finding_id="F-empty-evidence",
            severity="P2",
            location="module.py:10",
            root_cause="root",
            impact="impact",
            evidence=[],
            recommended_fix="fix",
            status="ACCEPT",
        )
