from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


SCHEMA_VERSION = "ralph_memory_node_v2"
ALLOWED_SENSITIVITY = {"GREEN", "YELLOW"}
REQUIRED_AUTHORITY = "non_authoritative"
VISIBILITY_VALUES = {"branch_local", "merge_candidate", "main_promoted", "deprecated_on_merge", "conflict"}
LINK_RELATIONS = {"supports", "contradicts", "updates", "supersedes", "same_topic", "depends_on"}
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class MemoryNodeError(ValueError):
    pass


class MemoryNodeValidationError(MemoryNodeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_identifier(value: object, label: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise MemoryNodeValidationError(f"{label} is required")
    if text.startswith("/") or "\\" in text or "/" in text or ".." in text:
        raise MemoryNodeValidationError(f"{label} is not a safe path segment")
    if not SAFE_ID_RE.fullmatch(text):
        raise MemoryNodeValidationError(f"{label} contains unsupported characters")
    return text


def _red_terms() -> tuple[str, ...]:
    return (
        "api" + "_key",
        "tok" + "en",
        "access" + "_token",
        "refresh" + "_token",
        "client" + "_secret",
        "pass" + "word",
        "cred" + "ential",
        "private" + "_key",
        "database" + "_url",
        "wallet",
        "seed" + "_phrase",
        "mnemonic",
    )


def contains_red_material(value: object) -> bool:
    text = "" if value is None else str(value)
    lowered = text.lower()
    if ".env" in lowered:
        return True
    for term in _red_terms():
        label = term.replace("_", r"[_-]?")
        pattern = re.compile(rf"(?<![A-Za-z0-9_])['\"`]?{label}['\"`]?\s*[:=]", re.IGNORECASE)
        if pattern.search(text):
            return True
    if re.search(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b", text):
        return True
    if re.search(r"(?i)\bbearer\b\s*[:=]?\s*[A-Za-z0-9_.-]{16,}", text):
        return True
    return False


def assert_not_red(value: object, label: str) -> None:
    if contains_red_material(value):
        raise MemoryNodeValidationError(f"{label} contains RED material")


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def deterministic_node_id(payload: dict[str, Any]) -> str:
    material = {
        "project_id": payload.get("project_id", ""),
        "memory_type": payload.get("memory_type", ""),
        "summary": payload.get("summary", ""),
        "source_paths": payload.get("source_paths", []),
        "source_description": payload.get("source_description", ""),
    }
    return "node_" + sha256_text(canonical_json(material))[:32]


@dataclass(frozen=True)
class MemoryNode:
    schema_version: str
    node_id: str
    project_id: str
    workspace_instance_id: str
    repo_remote_hash: str
    branch: str
    commit: str
    session_id: str
    memory_type: str
    sensitivity: str
    authority: str
    summary: str
    created_on_branch: str = ""
    visibility: str = "branch_local"
    promotion_status: str = "not_promoted"
    promotion_evidence: dict[str, Any] = field(default_factory=dict)
    detailed_summary: str = ""
    trigger: dict[str, Any] = field(default_factory=dict)
    topic_tags: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    source_paths: list[str] = field(default_factory=list)
    source_description: str = ""
    raw_ref: dict[str, Any] | None = None
    links: list[dict[str, Any]] = field(default_factory=list)
    salience: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    compaction_reason: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryNode":
        data = dict(payload)
        data.setdefault("schema_version", SCHEMA_VERSION)
        data.setdefault("node_id", deterministic_node_id(data))
        data.setdefault("created_on_branch", data.get("branch", ""))
        data.setdefault("visibility", "branch_local")
        data.setdefault("promotion_status", "not_promoted")
        data.setdefault("promotion_evidence", {})
        data.setdefault("detailed_summary", "")
        data.setdefault("trigger", {})
        data.setdefault("topic_tags", [])
        data.setdefault("entities", [])
        data.setdefault("source_paths", [])
        data.setdefault("source_description", "")
        data.setdefault("raw_ref", None)
        data.setdefault("links", [])
        data.setdefault("salience", {})
        data.setdefault("quality", {})
        stamp = now_iso()
        data.setdefault("created_at", stamp)
        data.setdefault("updated_at", data.get("created_at") or stamp)
        data.setdefault("compaction_reason", "")
        return validate_node(cls(**{field_name: data.get(field_name) for field_name in cls.__dataclass_fields__}))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _confidence(node: MemoryNode) -> float:
    value = node.quality.get("confidence") if isinstance(node.quality, dict) else None
    if value is None:
        raise MemoryNodeValidationError("quality.confidence is required")
    try:
        confidence = float(value)
    except (TypeError, ValueError) as exc:
        raise MemoryNodeValidationError("quality.confidence must be numeric") from exc
    if not 0.0 <= confidence <= 1.0:
        raise MemoryNodeValidationError("quality.confidence must be between 0 and 1")
    return confidence


def _validate_raw_ref(raw_ref: dict[str, Any] | None) -> None:
    if raw_ref is None:
        return
    if not isinstance(raw_ref, dict):
        raise MemoryNodeValidationError("raw_ref must be an object or null")
    if raw_ref.get("unsafe") is True or raw_ref.get("safe") is False:
        raise MemoryNodeValidationError("raw_ref is marked unsafe")
    digest = raw_ref.get("sha256")
    if digest is not None and not re.fullmatch(r"[a-f0-9]{64}", str(digest)):
        raise MemoryNodeValidationError("raw_ref.sha256 must be a sha256 hex digest")


def _validate_string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list):
        raise MemoryNodeValidationError(f"{label} must be a list")
    output: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            assert_not_red(text, label)
            output.append(text)
    return output


def _validate_links(value: object) -> None:
    if not isinstance(value, list):
        raise MemoryNodeValidationError("links must be a list")
    for item in value:
        if not isinstance(item, dict):
            raise MemoryNodeValidationError("links entries must be objects")
        relation = str(item.get("relation", "")).strip()
        if relation and relation not in LINK_RELATIONS:
            raise MemoryNodeValidationError("links relation is invalid")
        target = item.get("target_node_id", item.get("node_id"))
        if target:
            safe_identifier(target, "links.node_id")
        assert_not_red(item, "links")


def validate_node(node: MemoryNode) -> MemoryNode:
    if node.schema_version != SCHEMA_VERSION:
        raise MemoryNodeValidationError(f"schema_version must be {SCHEMA_VERSION}")
    safe_identifier(node.node_id, "node_id")
    safe_identifier(node.project_id, "project_id")
    if not str(node.branch or "").strip():
        raise MemoryNodeValidationError("branch is required")
    if not str(node.created_on_branch or "").strip():
        raise MemoryNodeValidationError("created_on_branch is required")
    if node.visibility not in VISIBILITY_VALUES:
        raise MemoryNodeValidationError("visibility is invalid")
    if not isinstance(node.promotion_evidence, dict):
        raise MemoryNodeValidationError("promotion_evidence must be an object")
    if not str(node.session_id or "").strip() and not str(node.commit or "").strip():
        raise MemoryNodeValidationError("session_id or commit is required")
    if not node.source_paths and not str(node.source_description or "").strip():
        raise MemoryNodeValidationError("source_paths or source_description is required")
    if node.sensitivity not in ALLOWED_SENSITIVITY:
        raise MemoryNodeValidationError("sensitivity must be GREEN or YELLOW")
    if node.authority != REQUIRED_AUTHORITY:
        raise MemoryNodeValidationError("authority must be non_authoritative")
    if not str(node.summary or "").strip():
        raise MemoryNodeValidationError("summary is required")
    if not isinstance(node.trigger, dict):
        raise MemoryNodeValidationError("trigger must be an object")
    if not isinstance(node.salience, dict):
        raise MemoryNodeValidationError("salience must be an object")
    if not isinstance(node.quality, dict):
        raise MemoryNodeValidationError("quality must be an object")
    if node.memory_type == "negative_rule" and (not node.quality.get("reason") or not node.quality.get("validation_evidence")):
        raise MemoryNodeValidationError("negative_rule requires reason and validation_evidence")
    if node.memory_type == "hub" and (node.raw_ref is not None or node.quality.get("synthetic") is not True):
        raise MemoryNodeValidationError("hub nodes must be synthetic and raw-free")
    _confidence(node)
    _validate_raw_ref(node.raw_ref)
    _validate_links(node.links)
    _validate_string_list(node.source_paths, "source_paths")
    for label, value in (
        ("summary", node.summary),
        ("detailed_summary", node.detailed_summary),
        ("created_on_branch", node.created_on_branch),
        ("visibility", node.visibility),
        ("promotion_status", node.promotion_status),
        ("promotion_evidence", node.promotion_evidence),
        ("source_description", node.source_description),
        ("trigger", node.trigger),
        ("topic_tags", node.topic_tags),
        ("entities", node.entities),
        ("compaction_reason", node.compaction_reason),
    ):
        assert_not_red(value, label)
    return node
