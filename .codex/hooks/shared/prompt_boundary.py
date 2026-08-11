"""Deterministic Prompt Boundary classification for Convergent Execution v4.

The classifier consumes only bounded prompt metadata and returns a content-free
contract.  Prompt length is never a boundary trigger by itself; explicit
intent, scope, obligation, and approval signals are considered separately.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any, Mapping


BOUNDARY_KINDS = frozenset(
    {"new_task", "continuation", "material_change", "status_only", "user_override", "clarification", "scope_extension"}
)
_POLICY_KIND_ALIASES = {
    "status": "status_only",
    "new-task": "new_task",
    "scope-extension": "scope_extension",
    "material-change": "material_change",
    "user-override": "user_override",
}
_STATUS = re.compile(r"\b(status|progress|current phase|where are we|estado|progreso|fase actual)\b", re.I)
_CONTINUE = re.compile(r"\b(continue|continuation|proceed|resume|next step|sigue|continuar|reanuda|adelante)\b", re.I)
_CLARIFY = re.compile(r"\b(clarif|question|duda|aclar|what do you mean|explain)\b", re.I)
_MATERIAL = re.compile(r"\b(material|architecture|architectural|contradict|new evidence|requirements? changed|redesign|trust boundary|scope changed|evidencia nueva|arquitectura|replantea)\b", re.I)
_SCOPE = re.compile(r"\b(also|additionally|include|extend|expand|plus|adem[aá]s|incluye|ampl[ií]a|extiende)\b", re.I)
_OVERRIDE = re.compile(r"\b(override|reconsider|second audit|reanalyze|re-?analiza|cambia el modelo|change model|ignore the plan)\b", re.I)
_CRITICAL = re.compile(r"\b(authori[sz]|permission|security|secret|credential|migration|migraci[oó]n|production|prod|persist|schema|concurren|public contract|trust boundary|egress|autorizaci[oó]n)\b", re.I)
_IMPLEMENT = re.compile(r"\b(implement|fix|patch|refactor|build|create|modify|corrige|implementa|crea|cambia|arregla)\b", re.I)


@dataclass(frozen=True)
class PromptBoundary:
    boundary_kind: str
    risk: str
    complexity: int
    scope_delta: bool
    obligation_delta: bool
    approval_delta: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_boundary(prompt: str, payload: Mapping[str, object] | None = None) -> PromptBoundary:
    payload = payload or {}
    bounded = prompt if isinstance(prompt, str) else ""
    explicit = _explicit_kind(payload)
    lowered = bounded.lower()
    override_signal = _truthy(payload, "user_override", "userOverride") or bool(_OVERRIDE.search(bounded))
    override_signal = override_signal or explicit == "user_override"
    critical = bool(_CRITICAL.search(bounded)) or _truthy(payload, "approval_delta", "approvalDelta") or override_signal
    material = bool(_MATERIAL.search(bounded)) or explicit == "material_change"
    scope_delta = bool(_SCOPE.search(bounded)) or _truthy(payload, "scope_delta", "scopeDelta") or explicit == "scope_extension"
    obligation_delta = bool(re.search(r"\b(must|required|done when|acceptance|obligaci[oó]n|criterio)\b", bounded, re.I)) or _truthy(payload, "obligation_delta", "obligationDelta")
    approval_delta = critical or _truthy(payload, "approval_delta", "approvalDelta", "requires_approval", "requiresApproval")

    if explicit:
        kind = explicit
    elif override_signal:
        kind = "user_override"
    elif material and (_truthy(payload, "active_task", "activeTask") or _truthy(payload, "material_change", "materialChange")):
        kind = "material_change"
    elif scope_delta and _truthy(payload, "active_task", "activeTask"):
        kind = "scope_extension"
    elif _STATUS.search(bounded) and not (_IMPLEMENT.search(bounded) or material or scope_delta):
        kind = "status_only"
    elif _CONTINUE.search(bounded) or _truthy(payload, "continuation", "isContinuation"):
        kind = "continuation"
    elif _CLARIFY.search(bounded) or (bounded.rstrip().endswith("?") and not (_IMPLEMENT.search(bounded) or critical)):
        kind = "clarification"
    else:
        kind = "new_task"

    risk = "critical" if critical else "material" if material or scope_delta or obligation_delta else "low"
    supplied_complexity = payload.get("complexity")
    if isinstance(supplied_complexity, int) and not isinstance(supplied_complexity, bool) and 1 <= supplied_complexity <= 8:
        complexity = supplied_complexity
    elif risk == "critical":
        complexity = 6
    elif risk == "material":
        complexity = 4
    else:
        complexity = 1
    # Long mechanical requests remain low complexity unless they carry an
    # independent material/critical signal.
    return PromptBoundary(kind, risk, complexity, bool(scope_delta), bool(obligation_delta), bool(approval_delta))


def _explicit_kind(payload: Mapping[str, object]) -> str:
    for key in ("boundary_kind", "boundaryKind", "prompt_boundary", "promptBoundary"):
        value = payload.get(key)
        if isinstance(value, str):
            candidate = value.strip()
            if candidate in BOUNDARY_KINDS:
                return candidate
            if candidate in _POLICY_KIND_ALIASES:
                return _POLICY_KIND_ALIASES[candidate]
        if isinstance(value, Mapping):
            nested = value.get("boundary_kind") or value.get("boundaryKind")
            if isinstance(nested, str):
                candidate = nested.strip()
                if candidate in BOUNDARY_KINDS:
                    return candidate
                if candidate in _POLICY_KIND_ALIASES:
                    return _POLICY_KIND_ALIASES[candidate]
    return ""


def _truthy(payload: Mapping[str, object], *keys: str) -> bool:
    return any(payload.get(key) is True for key in keys)


__all__ = ["BOUNDARY_KINDS", "PromptBoundary", "classify_boundary"]
