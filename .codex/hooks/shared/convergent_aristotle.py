"""Deterministic tier selection and output contract for v4 Aristotle."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .convergent_contracts import SHA256_RE, digest_value
from .decision_packet import DecisionPacket, DecisionPacketError
from .execution_policy import ExecutionPolicy
from .redaction import is_red


CRITICAL_DOMAINS = frozenset(
    {"authorization", "security", "persistence", "migration", "concurrency", "public-contract", "production"}
)
MICRO_SECTIONS = ("objective", "assumption", "risk", "done_when")
QUICK_SECTIONS = ("assumptions", "constraints", "proposed_move", "falsification_test")
FULL_SECTIONS = (
    "assumption_autopsy",
    "irreducible_truths",
    "reconstruction",
    "system_map",
    "selected_move",
    "decision_packet",
)
CRITICAL_SECTIONS = (
    *FULL_SECTIONS,
    "threat_boundaries",
    "failure_modes",
    "migration_compatibility",
    "rollout",
    "rollback",
    "observability",
    "abort_conditions",
)


class AristotleContractError(ValueError):
    """Raised when tier inputs or declared output violate the v4 contract."""


@dataclass(frozen=True)
class AristotleDecision:
    tier: str
    complexity: int
    risk: str
    critical_domains: tuple[str, ...]
    required_sections: tuple[str, ...]
    produces_decision_packet: bool
    decision_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "complexity": self.complexity,
            "risk": self.risk,
            "critical_domains": list(self.critical_domains),
            "required_sections": list(self.required_sections),
            "produces_decision_packet": self.produces_decision_packet,
            "decision_digest": self.decision_digest,
        }


@dataclass(frozen=True)
class AristotleEvidence:
    schema_version: int
    task_epoch: str
    tier: str
    decision_version: int
    tier_decision_digest: str
    section_digests: Mapping[str, str]
    evidence_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_epoch": self.task_epoch,
            "tier": self.tier,
            "decision_version": self.decision_version,
            "tier_decision_digest": self.tier_decision_digest,
            "section_digests": dict(self.section_digests),
            "evidence_digest": self.evidence_digest,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "AristotleEvidence":
        expected = {
            "schema_version",
            "task_epoch",
            "tier",
            "decision_version",
            "tier_decision_digest",
            "section_digests",
            "evidence_digest",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise AristotleContractError("Aristotle evidence key mismatch")
        version = value.get("decision_version")
        sections = value.get("section_digests")
        if value.get("schema_version") != 1 or isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise AristotleContractError("Aristotle evidence version is invalid")
        if not isinstance(value.get("task_epoch"), str) or not value["task_epoch"]:
            raise AristotleContractError("Aristotle evidence task epoch is invalid")
        if value.get("tier") not in {"micro", "quick", "full", "critical"}:
            raise AristotleContractError("Aristotle evidence tier is invalid")
        if not isinstance(sections, Mapping) or not sections or any(
            not isinstance(key, str) or not isinstance(item, str) or not SHA256_RE.fullmatch(item)
            for key, item in sections.items()
        ):
            raise AristotleContractError("Aristotle evidence section digests are invalid")
        if not isinstance(value.get("tier_decision_digest"), str) or not SHA256_RE.fullmatch(
            str(value["tier_decision_digest"])
        ):
            raise AristotleContractError("Aristotle tier decision digest is invalid")
        material = {key: value[key] for key in expected - {"evidence_digest"}}
        if value.get("evidence_digest") != digest_value(material):
            raise AristotleContractError("Aristotle evidence digest mismatch")
        return cls(
            schema_version=1,
            task_epoch=str(value["task_epoch"]),
            tier=str(value["tier"]),
            decision_version=version,
            tier_decision_digest=str(value["tier_decision_digest"]),
            section_digests=dict(sections),
            evidence_digest=str(value["evidence_digest"]),
        )


def select_aristotle_tier(
    *,
    complexity: int,
    risk: str,
    critical_domains: Sequence[str] = (),
    policy: ExecutionPolicy,
) -> AristotleDecision:
    if isinstance(complexity, bool) or not isinstance(complexity, int) or not 1 <= complexity <= 8:
        raise AristotleContractError("Aristotle complexity must be between 1 and 8")
    if risk not in {"low", "material", "critical"}:
        raise AristotleContractError("Aristotle risk is invalid")
    if not isinstance(critical_domains, (list, tuple)) or len(critical_domains) > len(CRITICAL_DOMAINS):
        raise AristotleContractError("critical domains must be a bounded list")
    domains = tuple(sorted(critical_domains))
    if len(set(domains)) != len(domains) or set(domains) - CRITICAL_DOMAINS:
        raise AristotleContractError("critical domains are duplicated or unsupported")
    config = policy.section("aristotle")
    if domains or risk == "critical":
        tier = "critical"
        normalized_risk = "critical"
        sections = CRITICAL_SECTIONS
    elif risk == "material" or complexity >= int(config["full_min_complexity"]):
        tier = "full"
        normalized_risk = "material" if risk == "low" else risk
        sections = FULL_SECTIONS
    elif complexity == int(config["quick_complexity"]):
        tier = "quick"
        normalized_risk = risk
        sections = QUICK_SECTIONS
    elif complexity <= int(config["micro_max_complexity"]):
        tier = "micro"
        normalized_risk = risk
        sections = MICRO_SECTIONS
    else:  # pragma: no cover - exact v4 thresholds cover complexity 1..8.
        raise AristotleContractError("execution policy leaves an uncovered Aristotle tier")
    material: dict[str, Any] = {
        "tier": tier,
        "complexity": complexity,
        "risk": normalized_risk,
        "critical_domains": list(domains),
        "required_sections": list(sections),
        "produces_decision_packet": tier in {"full", "critical"},
        "policy_hash": policy.policy_hash,
    }
    return AristotleDecision(
        tier=tier,
        complexity=complexity,
        risk=normalized_risk,
        critical_domains=domains,
        required_sections=sections,
        produces_decision_packet=material["produces_decision_packet"],
        decision_digest=digest_value(material),
    )


def validate_aristotle_output(decision: AristotleDecision, output: Mapping[str, object]) -> None:
    if not isinstance(output, Mapping):
        raise AristotleContractError("Aristotle output must be an object")
    unknown = sorted(set(output) - set(decision.required_sections))
    missing = sorted(set(decision.required_sections) - set(output))
    if unknown or missing:
        raise AristotleContractError(f"Aristotle output mismatch: unknown={unknown} missing={missing}")
    for section in decision.required_sections:
        value = output[section]
        if value is None or (isinstance(value, str) and not value.strip()) or value in ((), [], {}):
            raise AristotleContractError(f"Aristotle output section {section} is empty")
        _validate_output_value(value, label=f"Aristotle output section {section}", top_level=True)
    if decision.produces_decision_packet:
        packet = output.get("decision_packet")
        if not isinstance(packet, Mapping):
            raise AristotleContractError("Full/Critical Aristotle requires a structured Decision Packet")
        try:
            DecisionPacket.from_mapping(packet)
        except DecisionPacketError as exc:
            raise AristotleContractError("Full/Critical Aristotle Decision Packet is invalid") from exc


def validated_aristotle_evidence(
    decision: AristotleDecision,
    output: Mapping[str, object],
    *,
    task_epoch: str,
    decision_version: int,
) -> AristotleEvidence:
    """Validate output and freeze a bounded, content-free evidence artifact."""

    validate_aristotle_output(decision, output)
    if not task_epoch or len(task_epoch) > 180 or isinstance(decision_version, bool) or decision_version < 1:
        raise AristotleContractError("Aristotle evidence binding is invalid")
    material: dict[str, Any] = {
        "schema_version": 1,
        "task_epoch": task_epoch,
        "tier": decision.tier,
        "decision_version": decision_version,
        "tier_decision_digest": decision.decision_digest,
        "section_digests": {section: digest_value(output[section]) for section in decision.required_sections},
    }
    return AristotleEvidence.from_mapping({**material, "evidence_digest": digest_value(material)})


def _validate_output_value(value: object, *, label: str, top_level: bool = False) -> None:
    if isinstance(value, str):
        if not value.strip() or len(value.encode("utf-8")) > 8_192 or is_red(value):
            raise AristotleContractError(f"{label} is oversized or RED")
        return
    if isinstance(value, Mapping):
        if len(value) > 128:
            raise AristotleContractError(f"{label} is oversized")
        for key, item in value.items():
            if not isinstance(key, str) or key.lower() in {
                "prompt",
                "raw_prompt",
                "body",
                "stdout",
                "stderr",
                "reviewer_output",
                "secret",
                "token",
                "credential",
            }:
                raise AristotleContractError(f"{label} contains a forbidden field")
            _validate_output_value(item, label=f"{label}.{key}")
        return
    if isinstance(value, (list, tuple)):
        if len(value) > 128:
            raise AristotleContractError(f"{label} is oversized")
        for index, item in enumerate(value):
            _validate_output_value(item, label=f"{label}[{index}]")
        return
    if not top_level and (value is None or isinstance(value, (bool, int, float))):
        return
    raise AristotleContractError(f"{label} must be non-empty text or structured evidence")


__all__ = [
    "CRITICAL_DOMAINS",
    "AristotleContractError",
    "AristotleDecision",
    "AristotleEvidence",
    "select_aristotle_tier",
    "validate_aristotle_output",
    "validated_aristotle_evidence",
]
