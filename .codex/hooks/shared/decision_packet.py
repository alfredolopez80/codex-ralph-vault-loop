"""Immutable v4 Decision Packet and append-only material amendment schemas."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .convergent_contracts import SHA256_RE, digest_value
from .redaction import is_red


MAX_TEXT = 2_000
MAX_ITEMS = 64
PACKET_FIELDS = (
    "decision_version",
    "task_epoch",
    "objective",
    "source_of_truth",
    "assumptions",
    "irreducible_truths",
    "root_cause",
    "invariants",
    "selected_solution",
    "rejected_alternatives",
    "affected_components",
    "implementation_sequence",
    "verification_matrix",
    "review_requirement",
    "security_and_rollout",
    "rollback",
    "done_when",
    "material_change_triggers",
    "analysis_fingerprint",
)


class DecisionPacketError(ValueError):
    """Raised when packet content is incomplete, unsafe, or non-deterministic."""


@dataclass(frozen=True)
class DecisionPacket:
    decision_version: int
    task_epoch: str
    objective: str
    source_of_truth: tuple[str, ...]
    assumptions: tuple[Mapping[str, Any], ...]
    irreducible_truths: tuple[Mapping[str, Any], ...]
    root_cause: str
    invariants: tuple[str, ...]
    selected_solution: str
    rejected_alternatives: tuple[str, ...]
    affected_components: tuple[str, ...]
    implementation_sequence: tuple[Mapping[str, Any], ...]
    verification_matrix: tuple[Mapping[str, Any], ...]
    review_requirement: Mapping[str, Any]
    security_and_rollout: Mapping[str, Any]
    rollback: Mapping[str, Any]
    done_when: tuple[str, ...]
    material_change_triggers: tuple[str, ...]
    analysis_fingerprint: str

    @classmethod
    def create(cls, **values: Any) -> "DecisionPacket":
        values = dict(values)
        values.pop("analysis_fingerprint", None)
        normalized = _normalize_packet(values)
        return cls(**_freeze_packet(normalized), analysis_fingerprint=digest_value(normalized))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DecisionPacket":
        unknown = sorted(set(value) - set(PACKET_FIELDS))
        missing = sorted(set(PACKET_FIELDS) - set(value))
        if unknown or missing:
            raise DecisionPacketError(f"Decision Packet key mismatch: unknown={unknown} missing={missing}")
        normalized = _normalize_packet({key: value[key] for key in PACKET_FIELDS if key != "analysis_fingerprint"})
        fingerprint = _digest(value.get("analysis_fingerprint"), "analysis_fingerprint")
        if fingerprint != digest_value(normalized):
            raise DecisionPacketError("Decision Packet fingerprint mismatch")
        return cls(**_freeze_packet(normalized), analysis_fingerprint=fingerprint)

    def as_dict(self) -> dict[str, Any]:
        return _thaw(
            {
                "decision_version": self.decision_version,
                "task_epoch": self.task_epoch,
                "objective": self.objective,
                "source_of_truth": list(self.source_of_truth),
                "assumptions": self.assumptions,
                "irreducible_truths": self.irreducible_truths,
                "root_cause": self.root_cause,
                "invariants": list(self.invariants),
                "selected_solution": self.selected_solution,
                "rejected_alternatives": list(self.rejected_alternatives),
                "affected_components": list(self.affected_components),
                "implementation_sequence": self.implementation_sequence,
                "verification_matrix": self.verification_matrix,
                "review_requirement": self.review_requirement,
                "security_and_rollout": self.security_and_rollout,
                "rollback": self.rollback,
                "done_when": list(self.done_when),
                "material_change_triggers": list(self.material_change_triggers),
                "analysis_fingerprint": self.analysis_fingerprint,
            }
        )


@dataclass(frozen=True)
class DecisionAmendment:
    amendment_id: str
    prior_packet_fingerprint: str
    new_evidence: tuple[str, ...]
    invalidated_assumption: str
    affected_invariants: tuple[str, ...]
    design_impact: str
    changed_steps: tuple[str, ...]
    unchanged_steps: tuple[str, ...]
    verification_changes: tuple[str, ...]
    approval_state: str
    new_fingerprint: str

    @classmethod
    def create(
        cls,
        *,
        amendment_id: str,
        prior_packet_fingerprint: str,
        new_evidence: Sequence[str],
        invalidated_assumption: str,
        affected_invariants: Sequence[str],
        design_impact: str,
        changed_steps: Sequence[str],
        unchanged_steps: Sequence[str],
        verification_changes: Sequence[str],
        approval_state: str,
    ) -> "DecisionAmendment":
        normalized = _normalize_amendment(
            {
                "amendment_id": amendment_id,
                "prior_packet_fingerprint": prior_packet_fingerprint,
                "new_evidence": new_evidence,
                "invalidated_assumption": invalidated_assumption,
                "affected_invariants": affected_invariants,
                "design_impact": design_impact,
                "changed_steps": changed_steps,
                "unchanged_steps": unchanged_steps,
                "verification_changes": verification_changes,
                "approval_state": approval_state,
            }
        )
        return cls._from_normalized(normalized, digest_value(normalized))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DecisionAmendment":
        expected = {
            "amendment_id",
            "prior_packet_fingerprint",
            "new_evidence",
            "invalidated_assumption",
            "affected_invariants",
            "design_impact",
            "changed_steps",
            "unchanged_steps",
            "verification_changes",
            "approval_state",
            "new_fingerprint",
        }
        if set(value) != expected:
            raise DecisionPacketError("Decision Amendment key mismatch")
        normalized = _normalize_amendment({key: value[key] for key in expected - {"new_fingerprint"}})
        fingerprint = _digest(value.get("new_fingerprint"), "new_fingerprint")
        if fingerprint != digest_value(normalized):
            raise DecisionPacketError("Decision Amendment fingerprint mismatch")
        return cls._from_normalized(normalized, fingerprint)

    @classmethod
    def _from_normalized(cls, normalized: Mapping[str, Any], fingerprint: str) -> "DecisionAmendment":
        return cls(
            amendment_id=str(normalized["amendment_id"]),
            prior_packet_fingerprint=str(normalized["prior_packet_fingerprint"]),
            new_evidence=tuple(normalized["new_evidence"]),
            invalidated_assumption=str(normalized["invalidated_assumption"]),
            affected_invariants=tuple(normalized["affected_invariants"]),
            design_impact=str(normalized["design_impact"]),
            changed_steps=tuple(normalized["changed_steps"]),
            unchanged_steps=tuple(normalized["unchanged_steps"]),
            verification_changes=tuple(normalized["verification_changes"]),
            approval_state=str(normalized["approval_state"]),
            new_fingerprint=fingerprint,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "amendment_id": self.amendment_id,
            "prior_packet_fingerprint": self.prior_packet_fingerprint,
            "new_evidence": list(self.new_evidence),
            "invalidated_assumption": self.invalidated_assumption,
            "affected_invariants": list(self.affected_invariants),
            "design_impact": self.design_impact,
            "changed_steps": list(self.changed_steps),
            "unchanged_steps": list(self.unchanged_steps),
            "verification_changes": list(self.verification_changes),
            "approval_state": self.approval_state,
            "new_fingerprint": self.new_fingerprint,
        }


def _normalize_packet(values: Mapping[str, Any]) -> dict[str, Any]:
    expected = set(PACKET_FIELDS) - {"analysis_fingerprint"}
    unknown = sorted(set(values) - expected)
    missing = sorted(expected - set(values))
    if unknown or missing:
        raise DecisionPacketError(f"Decision Packet key mismatch: unknown={unknown} missing={missing}")
    version = values.get("decision_version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise DecisionPacketError("decision_version must be positive")
    assumptions = _statements(values.get("assumptions"), "assumptions")
    truths = _statements(values.get("irreducible_truths"), "irreducible_truths")
    return {
        "decision_version": version,
        "task_epoch": _identifier(values.get("task_epoch"), "task_epoch"),
        "objective": _text(values.get("objective"), "objective"),
        "source_of_truth": list(_items(values.get("source_of_truth"), "source_of_truth")),
        "assumptions": assumptions,
        "irreducible_truths": truths,
        "root_cause": _text(values.get("root_cause"), "root_cause"),
        "invariants": list(_items(values.get("invariants"), "invariants")),
        "selected_solution": _text(values.get("selected_solution"), "selected_solution"),
        "rejected_alternatives": list(_items(values.get("rejected_alternatives"), "rejected_alternatives", allow_empty=True)),
        "affected_components": list(_items(values.get("affected_components"), "affected_components")),
        "implementation_sequence": _steps(values.get("implementation_sequence")),
        "verification_matrix": _gates(values.get("verification_matrix")),
        "review_requirement": _review(values.get("review_requirement")),
        "security_and_rollout": _security(values.get("security_and_rollout")),
        "rollback": _rollback(values.get("rollback")),
        "done_when": list(_items(values.get("done_when"), "done_when")),
        "material_change_triggers": list(_items(values.get("material_change_triggers"), "material_change_triggers")),
    }


def _normalize_amendment(values: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "amendment_id",
        "prior_packet_fingerprint",
        "new_evidence",
        "invalidated_assumption",
        "affected_invariants",
        "design_impact",
        "changed_steps",
        "unchanged_steps",
        "verification_changes",
        "approval_state",
    }
    if set(values) != expected:
        raise DecisionPacketError("Decision Amendment key mismatch")
    return {
        "amendment_id": _identifier(values.get("amendment_id"), "amendment_id"),
        "prior_packet_fingerprint": _digest(values.get("prior_packet_fingerprint"), "prior_packet_fingerprint"),
        "new_evidence": list(_items(values.get("new_evidence"), "new_evidence")),
        "invalidated_assumption": _text(values.get("invalidated_assumption"), "invalidated_assumption"),
        "affected_invariants": list(_items(values.get("affected_invariants"), "affected_invariants")),
        "design_impact": _text(values.get("design_impact"), "design_impact"),
        "changed_steps": list(_items(values.get("changed_steps"), "changed_steps")),
        "unchanged_steps": list(_items(values.get("unchanged_steps"), "unchanged_steps", allow_empty=True)),
        "verification_changes": list(_items(values.get("verification_changes"), "verification_changes")),
        "approval_state": _enum(
            values.get("approval_state"), {"implicit", "approved", "pending", "rejected"}, "approval_state"
        ),
    }


def _freeze_packet(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **value,
        "source_of_truth": tuple(value["source_of_truth"]),
        "assumptions": tuple(_freeze(item) for item in value["assumptions"]),
        "irreducible_truths": tuple(_freeze(item) for item in value["irreducible_truths"]),
        "invariants": tuple(value["invariants"]),
        "rejected_alternatives": tuple(value["rejected_alternatives"]),
        "affected_components": tuple(value["affected_components"]),
        "implementation_sequence": tuple(_freeze(item) for item in value["implementation_sequence"]),
        "verification_matrix": tuple(_freeze(item) for item in value["verification_matrix"]),
        "review_requirement": _freeze(value["review_requirement"]),
        "security_and_rollout": _freeze(value["security_and_rollout"]),
        "rollback": _freeze(value["rollback"]),
        "done_when": tuple(value["done_when"]),
        "material_change_triggers": tuple(value["material_change_triggers"]),
    }


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _statements(value: object, label: str) -> list[dict[str, Any]]:
    rows = _mapping_list(value, label)
    normalized: list[dict[str, Any]] = []
    ids: set[str] = set()
    for row in rows:
        _keys(row, {"id", "statement", "evidence_refs"}, label)
        identifier = _identifier(row.get("id"), f"{label}.id")
        if identifier in ids:
            raise DecisionPacketError(f"{label} IDs must be unique")
        ids.add(identifier)
        normalized.append(
            {
                "id": identifier,
                "statement": _text(row.get("statement"), f"{label}.statement"),
                "evidence_refs": list(_items(row.get("evidence_refs"), f"{label}.evidence_refs", allow_empty=True)),
            }
        )
    return normalized


def _steps(value: object) -> list[dict[str, Any]]:
    rows = _mapping_list(value, "implementation_sequence")
    result: list[dict[str, Any]] = []
    for row in rows:
        _keys(row, {"step_id", "goal_id", "preconditions", "outputs"}, "implementation_sequence")
        result.append(
            {
                "step_id": _identifier(row.get("step_id"), "step_id"),
                "goal_id": _identifier(row.get("goal_id"), "goal_id"),
                "preconditions": list(_items(row.get("preconditions"), "preconditions", allow_empty=True)),
                "outputs": list(_items(row.get("outputs"), "outputs")),
            }
        )
    if len({row["step_id"] for row in result}) != len(result):
        raise DecisionPacketError("implementation step IDs must be unique")
    return result


def _gates(value: object) -> list[dict[str, Any]]:
    rows = _mapping_list(value, "verification_matrix")
    result: list[dict[str, Any]] = []
    for row in rows:
        _keys(row, {"gate", "command", "expected", "evidence_path", "blocking"}, "verification_matrix")
        blocking = row.get("blocking")
        if not isinstance(blocking, bool):
            raise DecisionPacketError("verification gate blocking must be boolean")
        result.append(
            {
                "gate": _identifier(row.get("gate"), "verification gate"),
                "command": _text(row.get("command"), "verification command"),
                "expected": _text(row.get("expected"), "verification expected"),
                "evidence_path": _text(row.get("evidence_path"), "verification evidence_path"),
                "blocking": blocking,
            }
        )
    if len({row["gate"] for row in result}) != len(result):
        raise DecisionPacketError("verification gate IDs must be unique")
    return result


def _review(value: object) -> dict[str, Any]:
    row = _mapping(value, "review_requirement")
    _keys(row, {"required", "risk", "owner", "max_passes"}, "review_requirement")
    required = row.get("required")
    maximum = row.get("max_passes")
    if not isinstance(required, bool) or isinstance(maximum, bool) or not isinstance(maximum, int) or maximum not in {0, 1}:
        raise DecisionPacketError("review requirement booleans/budget are invalid")
    risk = _enum(row.get("risk"), {"low", "material", "critical"}, "review risk")
    if (risk == "low" and (required or maximum)) or (risk != "low" and (not required or maximum != 1)):
        raise DecisionPacketError("review requirement violates the 0/1 risk budget")
    return {"required": required, "risk": risk, "owner": _identifier(row.get("owner"), "review owner"), "max_passes": maximum}


def _security(value: object) -> dict[str, Any]:
    row = _mapping(value, "security_and_rollout")
    _keys(row, {"threat_boundaries", "rollout", "observability"}, "security_and_rollout")
    return {
        "threat_boundaries": list(_items(row.get("threat_boundaries"), "threat_boundaries", allow_empty=True)),
        "rollout": list(_items(row.get("rollout"), "rollout")),
        "observability": list(_items(row.get("observability"), "observability")),
    }


def _rollback(value: object) -> dict[str, Any]:
    row = _mapping(value, "rollback")
    _keys(row, {"triggers", "steps", "preserve"}, "rollback")
    return {
        "triggers": list(_items(row.get("triggers"), "rollback.triggers")),
        "steps": list(_items(row.get("steps"), "rollback.steps")),
        "preserve": list(_items(row.get("preserve"), "rollback.preserve")),
    }


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DecisionPacketError(f"{label} must be an object")
    return value


def _mapping_list(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, (list, tuple)) or not value or len(value) > MAX_ITEMS or any(not isinstance(item, Mapping) for item in value):
        raise DecisionPacketError(f"{label} must be a non-empty bounded object list")
    return list(value)


def _keys(row: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(row) != expected:
        raise DecisionPacketError(f"{label} has unknown or missing keys")


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > MAX_TEXT:
        raise DecisionPacketError(f"{label} must be non-empty and bounded")
    result = value.strip()
    if is_red(result):
        raise DecisionPacketError(f"{label} contains RED material")
    return result


def _items(value: object, label: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > MAX_ITEMS or (not value and not allow_empty):
        raise DecisionPacketError(f"{label} must be a bounded list")
    result = tuple(_text(item, f"{label} item") for item in value)
    if len(set(result)) != len(result):
        raise DecisionPacketError(f"{label} contains duplicates")
    return result


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 180 or any(char.isspace() for char in value):
        raise DecisionPacketError(f"{label} must be a safe identifier")
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise DecisionPacketError(f"{label} must be a sha256 digest")
    return value


def _enum(value: object, allowed: set[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise DecisionPacketError(f"{label} has an unsupported value")
    return value


__all__ = ["DecisionAmendment", "DecisionPacket", "DecisionPacketError", "PACKET_FIELDS"]
