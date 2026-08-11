"""Deterministic tier selection and output contract for v4 Aristotle."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .convergent_contracts import digest_value
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
    "select_aristotle_tier",
    "validate_aristotle_output",
]
