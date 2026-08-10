"""Content-free task identities for prompt-context reuse."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Mapping

from .active_context import ActiveContext
from .runtime_profile import RuntimeProfile


SCHEMA_VERSION = 1
_INTENT_RULES = (
    ("security", re.compile(r"\b(security|vulnerab|secret|credential|seguridad|secreto|credencial)\b", re.I)),
    ("migration", re.compile(r"\b(migrat|rollout|deploy|migraci[oó]n|despliegue)\b", re.I)),
    ("debug", re.compile(r"\b(debug|diagnos|root cause|failure|error|fallo)\b", re.I)),
    ("review", re.compile(r"\b(review|audit|revisa|audita)\b", re.I)),
    ("implementation", re.compile(r"\b(implement|fix|patch|refactor|create|modify|corrige|crea|cambia)\b", re.I)),
    ("documentation", re.compile(r"\b(document|readme|docs)\b", re.I)),
)


def _digest(value: str, length: int = 32) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:length]


def normalized_intent(prompt: str) -> str:
    for name, pattern in _INTENT_RULES:
        if pattern.search(prompt):
            return name
    return "question" if prompt.rstrip().endswith("?") else "routine"


@dataclass(frozen=True)
class TaskSignature:
    schema_version: int
    value: str
    anchor: str
    project_id: str
    workspace_instance_id: str
    branch: str
    head: str
    prompt_hash: str
    intent: str
    sensitivity: str
    model_family: str
    checkpoint_identity: str
    model_source: str = "unknown"
    model_verified: bool = False

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def signature_from_prompt(
    prompt: str,
    *,
    context: ActiveContext,
    profile: RuntimeProfile,
    sensitivity: str,
    checkpoint_identity: str = "",
    progress_plan_id: str = "",
    progress_generation: int = 0,
    context_epoch: str = "",
) -> TaskSignature:
    prompt_hash = _digest(prompt, 40)
    checkpoint_material = {
        "checkpoint": checkpoint_identity,
        "progress_plan_id": progress_plan_id,
        "progress_generation": max(0, int(progress_generation or 0)),
        "context_epoch": context_epoch,
    }
    checkpoint = _digest(json.dumps(checkpoint_material, sort_keys=True, separators=(",", ":")), 24) if any(checkpoint_material.values()) else ""
    intent = normalized_intent(prompt)
    anchor_material = {
        "schema_version": SCHEMA_VERSION,
        "project_id": context.project_id,
        "workspace_instance_id": context.workspace_instance_id,
        "branch": context.branch,
        "prompt_hash": prompt_hash,
        "intent": intent,
        "sensitivity": sensitivity,
        "model_family": profile.model_family,
        "model_source": profile.model_source,
        "model_verified": profile.model_verified,
    }
    anchor = _digest(json.dumps(anchor_material, sort_keys=True, separators=(",", ":")))
    value_material = {
        **anchor_material,
        "head": context.sha,
        "model_family": profile.model_family,
        "model_source": profile.model_source,
        "model_verified": profile.model_verified,
        "checkpoint_identity": checkpoint,
    }
    return TaskSignature(
        schema_version=SCHEMA_VERSION,
        value=f"task-{_digest(json.dumps(value_material, sort_keys=True, separators=(',', ':')))}",
        anchor=f"anchor-{anchor}",
        project_id=context.project_id,
        workspace_instance_id=context.workspace_instance_id,
        branch=context.branch,
        head=context.sha,
        prompt_hash=prompt_hash,
        intent=intent,
        sensitivity=sensitivity,
        model_family=profile.model_family,
        checkpoint_identity=checkpoint,
        model_source=profile.model_source,
        model_verified=profile.model_verified,
    )


def safe_serialization(signature: TaskSignature) -> str:
    return json.dumps(signature.as_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


__all__ = ["SCHEMA_VERSION", "TaskSignature", "normalized_intent", "safe_serialization", "signature_from_prompt"]
