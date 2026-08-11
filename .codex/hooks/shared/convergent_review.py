"""Bounded review, finding ledger, and one-batch mitigation contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .convergent_contracts import digest_value
from .redaction import is_red


FINDING_SEVERITIES = frozenset({"P0", "P1", "P2", "P3"})
FINDING_STATUSES = frozenset({"ACCEPT", "REJECT_FALSE_POSITIVE", "PRE_EXISTING", "DEFER_FOLLOW_UP", "NEEDS_USER_DECISION"})
REVIEW_RISKS = frozenset({"low", "material", "critical"})


class ReviewContractError(ValueError):
    """Raised when a review ledger violates the v4 budget or evidence shape."""


@dataclass(frozen=True)
class Finding:
    finding_id: str
    severity: str
    location: str
    root_cause: str
    impact: str
    evidence: tuple[str, ...]
    recommended_fix: str
    status: str

    @classmethod
    def create(cls, **values: Any) -> "Finding":
        required = {"finding_id", "severity", "location", "root_cause", "impact", "evidence", "recommended_fix", "status"}
        if set(values) != required:
            raise ReviewContractError("finding fields are incomplete or unknown")
        identifier = _text_id(values["finding_id"], "finding_id")
        severity = _enum(values["severity"], FINDING_SEVERITIES, "severity")
        status = _enum(values["status"], FINDING_STATUSES, "status")
        evidence = _ids(values["evidence"], "evidence")
        return cls(
            identifier,
            severity,
            _text(values["location"], "location"),
            _text(values["root_cause"], "root_cause"),
            _text(values["impact"], "impact"),
            evidence,
            _text(values["recommended_fix"], "recommended_fix"),
            status,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "severity": self.severity,
            "location": self.location,
            "root_cause": self.root_cause,
            "impact": self.impact,
            "evidence": list(self.evidence),
            "recommended_fix": self.recommended_fix,
            "status": self.status,
        }


@dataclass(frozen=True)
class ReviewLedger:
    risk: str
    owner: str
    pass_number: int
    findings: tuple[Finding, ...]
    findings_digest: str

    @classmethod
    def create(cls, *, risk: str, findings: Sequence[Finding], owner: str = "reviewer", pass_number: int = 1, prior_passes: int = 0) -> "ReviewLedger":
        risk = _enum(risk, REVIEW_RISKS, "review risk")
        owner = _text_id(owner, "review owner")
        if isinstance(pass_number, bool) or not isinstance(pass_number, int) or pass_number < 1:
            raise ReviewContractError("review pass must be positive")
        if isinstance(prior_passes, bool) or not isinstance(prior_passes, int) or prior_passes < 0:
            raise ReviewContractError("prior review passes must be nonnegative")
        maximum = 0 if risk == "low" else 1
        if maximum == 0 or prior_passes >= maximum or pass_number > maximum:
            raise ReviewContractError("review budget exhausted or low-risk review is forbidden")
        if not isinstance(findings, (list, tuple)) or any(not isinstance(item, Finding) for item in findings):
            raise ReviewContractError("finding ledger items must be structured Finding values")
        if len(findings) > 128 or len({item.finding_id for item in findings}) != len(findings):
            raise ReviewContractError("finding ledger is unbounded or contains duplicate IDs")
        normalized = tuple(findings)
        digest = digest_value({"risk": risk, "owner": owner, "pass_number": pass_number, "findings": [item.as_dict() for item in normalized]})
        return cls(risk, owner, pass_number, normalized, digest)

    def accepted(self) -> tuple[Finding, ...]:
        return tuple(item for item in self.findings if item.status == "ACCEPT")

    def mitigation_batches(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        grouped: dict[str, list[str]] = {}
        for finding in self.accepted():
            grouped.setdefault(finding.root_cause, []).append(finding.finding_id)
        return tuple((root, tuple(sorted(ids))) for root, ids in sorted(grouped.items()))

    def as_dict(self) -> dict[str, Any]:
        return {
            "risk": self.risk,
            "owner": self.owner,
            "pass_number": self.pass_number,
            "findings": [item.as_dict() for item in self.findings],
            "findings_digest": self.findings_digest,
        }


def triage_findings(findings: Sequence[Finding]) -> dict[str, tuple[str, ...]]:
    """Return all statuses and accepted IDs; no implicit status is invented."""

    if not isinstance(findings, (list, tuple)) or any(not isinstance(item, Finding) for item in findings):
        raise ReviewContractError("triage items must be structured Finding values")
    if len({item.finding_id for item in findings}) != len(findings):
        raise ReviewContractError("triage received duplicate finding IDs")
    grouped: dict[str, list[str]] = {status: [] for status in sorted(FINDING_STATUSES)}
    for item in findings:
        grouped[item.status].append(item.finding_id)
    return {status: tuple(sorted(ids)) for status, ids in grouped.items()}


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ReviewContractError(f"{label} must be text")
    clean = " ".join(value.replace("\x00", " ").split()).strip()
    if not clean or len(clean) > 2_000 or is_red(clean):
        raise ReviewContractError(f"{label} is empty, oversized, or RED")
    return clean


def _text_id(value: object, label: str) -> str:
    clean = _text(value, label)
    if len(clean) > 180 or any(char.isspace() for char in clean):
        raise ReviewContractError(f"{label} must be a bounded identifier")
    return clean


def _ids(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > 64:
        raise ReviewContractError(f"{label} must be a bounded identifier list")
    result = tuple(_text_id(item, f"{label} item") for item in value)
    if not result:
        raise ReviewContractError(f"{label} must contain at least one evidence identifier")
    if len(set(result)) != len(result):
        raise ReviewContractError(f"{label} contains duplicate identifiers")
    return result


def _enum(value: object, allowed: set[str] | frozenset[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ReviewContractError(f"{label} has an unsupported value")
    return value


# Compatibility-shaped ledger API used by the close reducer.  It keeps the
# wire names from the supplied finding contract while the smaller Finding /
# ReviewLedger API above remains convenient for callers that already have
# structured objects.
@dataclass(frozen=True)
class ReviewFinding:
    finding_id: str
    severity: str
    location: str
    root_cause: str
    impact: str
    evidence_ids: tuple[str, ...]
    recommendation: str
    triage_status: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ReviewFinding":
        expected = {"finding_id", "severity", "location", "root_cause", "impact", "evidence_ids", "recommendation", "triage_status"}
        unknown = set(value) - expected
        missing = expected - set(value)
        if unknown or missing:
            raise ReviewContractError(f"finding fields unknown or missing: unknown={sorted(unknown)} missing={sorted(missing)}")
        status = str(value["triage_status"])
        if status not in {"pending", "accepted", "rejected"}:
            raise ReviewContractError("finding triage status is invalid")
        return cls(
            _text_id(value["finding_id"], "finding_id"),
            _enum(value["severity"], FINDING_SEVERITIES, "severity"),
            _text(value["location"], "location"),
            _text(value["root_cause"], "root_cause"),
            _text(value["impact"], "impact"),
            _ids(value["evidence_ids"], "evidence_ids"),
            _text(value["recommendation"], "recommendation"),
            status,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id,
            "severity": self.severity,
            "location": self.location,
            "root_cause": self.root_cause,
            "impact": self.impact,
            "evidence_ids": list(self.evidence_ids),
            "recommendation": self.recommendation,
            "triage_status": self.triage_status,
        }


@dataclass(frozen=True)
class FindingLedger:
    risk: str
    review_pass: int
    review_owner: str
    findings: tuple[ReviewFinding, ...]
    findings_digest: str
    accepted_ids: tuple[str, ...] = ()

    @classmethod
    def create(cls, *, risk: str, review_pass: int, review_owner: str, findings: Sequence[ReviewFinding]) -> "FindingLedger":
        risk = _enum(risk, REVIEW_RISKS, "review risk")
        if isinstance(review_pass, bool) or not isinstance(review_pass, int) or review_pass < 0:
            raise ReviewContractError("review pass is invalid")
        if risk == "low" and review_pass != 0:
            raise ReviewContractError("low-risk work has zero automatic review")
        if risk != "low" and review_pass != 1:
            raise ReviewContractError("material review must consume exactly one pass")
        if not isinstance(findings, (list, tuple)) or any(not isinstance(item, ReviewFinding) for item in findings):
            raise ReviewContractError("finding ledger items must be structured ReviewFinding values")
        if len(findings) > 128:
            raise ReviewContractError("finding ledger is unbounded")
        normalized = tuple(findings)
        if len({item.finding_id for item in normalized}) != len(normalized):
            raise ReviewContractError("finding ledger contains duplicate IDs")
        normalized_owner = _text_id(review_owner, "review owner")
        accepted_ids = tuple(sorted(item.finding_id for item in normalized if item.triage_status == "accepted"))
        return cls(
            risk,
            review_pass,
            normalized_owner,
            normalized,
            digest_value({"risk": risk, "review_pass": review_pass, "review_owner": normalized_owner, "findings": [item.as_dict() for item in normalized]}),
            accepted_ids,
        )

    def triage(self, decisions: Mapping[str, str]) -> "FindingLedger":
        expected = {item.finding_id for item in self.findings}
        if set(decisions) != expected:
            raise ReviewContractError("every pending finding must be triaged")
        updated: list[ReviewFinding] = []
        for item in self.findings:
            decision = decisions[item.finding_id]
            if decision not in {"accepted", "rejected"}:
                raise ReviewContractError("finding triage decision is invalid")
            updated.append(ReviewFinding(**{**item.__dict__, "triage_status": decision}))
        accepted = tuple(item.finding_id for item in updated if item.triage_status == "accepted")
        return FindingLedger(
            self.risk,
            self.review_pass,
            self.review_owner,
            tuple(updated),
            digest_value({"risk": self.risk, "review_pass": self.review_pass, "review_owner": self.review_owner, "findings": [item.as_dict() for item in updated]}),
            accepted,
        )


@dataclass(frozen=True)
class MitigationBatch:
    finding_ids: tuple[str, ...]
    root_cause_groups: tuple[tuple[str, tuple[str, ...]], ...]
    batch_digest: str
    status: str = "open"

    @classmethod
    def create(cls, ledger: FindingLedger) -> "MitigationBatch":
        accepted = [item for item in ledger.findings if item.triage_status == "accepted"]
        grouped: dict[str, list[str]] = {}
        for item in accepted:
            grouped.setdefault(item.root_cause, []).append(item.finding_id)
        groups = tuple((root, tuple(sorted(ids))) for root, ids in sorted(grouped.items()))
        ids = tuple(sorted(item.finding_id for item in accepted))
        return cls(ids, groups, digest_value({"finding_ids": ids, "root_cause_groups": groups}))

    def close(self, finding_ids: Sequence[str]) -> "MitigationBatch":
        if set(finding_ids) != set(self.finding_ids):
            raise ReviewContractError("mitigation must close every accepted finding in one batch")
        return MitigationBatch(self.finding_ids, self.root_cause_groups, digest_value({"closed": list(self.finding_ids), "prior": self.batch_digest}), "closed")


__all__ = [
    "FINDING_SEVERITIES",
    "FINDING_STATUSES",
    "Finding",
    "FindingLedger",
    "MitigationBatch",
    "ReviewContractError",
    "ReviewFinding",
    "ReviewLedger",
    "triage_findings",
]
