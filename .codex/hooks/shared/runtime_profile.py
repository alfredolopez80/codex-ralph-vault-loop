"""Conservative, payload-first runtime profiles for hook context budgets.

The profile is deliberately small and side-effect free.  It never inspects a
transcript: model identity comes from the hook payload and only falls back to
an explicit environment value or the repository config.

Model provenance and the safety profile are intentionally separate. A
repository default can select conservative runtime limits, but it is not
evidence that the current turn uses that model: a per-turn selector may have
overridden it. Progress budgets therefore require verified provenance.
"""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .paths import REPO_ROOT


IMPLEMENTATION_PROGRESS_ORIGIN = "implementation-progress"
PROGRESS_MAINTENANCE_INTENT = "progress-maintenance"
PROGRESS_REASON_CODE = "local-deterministic-progress-maintenance"
MODEL_FAMILIES = frozenset({"luna", "terra", "sol", "unknown"})
MODEL_SOURCES = frozenset({"payload", "environment", "repository-default", "unknown"})


@dataclass(frozen=True)
class ModelProvenance:
    """Content-free model identity evidence used by cost policy."""

    model_family: str
    model_source: str
    model_verified: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProgressBudget:
    """UTF-8 byte limits for deterministic implementation-progress output."""

    recovery_bytes: int
    delta_bytes: int
    expanded_bytes: int
    advisor_budget: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class RuntimeProfile:
    name: str
    model_family: str
    prompt_context_bytes_soft: int
    prompt_context_bytes_hard: int
    session_context_bytes_soft: int
    session_context_bytes_hard: int
    recall_items: int
    recall_word_budget: int
    advisor_budget: int
    max_stop_continuations: int
    allow_prompt_improvement: bool
    allow_repeated_route_context: bool
    maintenance_mode: str
    # These fields are bound at resolution time. The constants below are
    # safety templates and deliberately carry unknown provenance.
    model_source: str = "unknown"
    model_verified: bool = False
    progress_recovery_bytes: int = 96
    progress_delta_bytes: int = 96
    progress_expanded_bytes: int = 96
    progress_advisor_budget: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def safety_profile(self) -> str:
        """Return the selected safety template without implying provenance."""
        return self.name

    @property
    def progress_budget(self) -> ProgressBudget:
        return ProgressBudget(
            recovery_bytes=self.progress_recovery_bytes,
            delta_bytes=self.progress_delta_bytes,
            expanded_bytes=self.progress_expanded_bytes,
            advisor_budget=self.progress_advisor_budget,
        )


LUNA = RuntimeProfile(
    name="luna",
    model_family="luna",
    prompt_context_bytes_soft=1_200,
    prompt_context_bytes_hard=1_800,
    session_context_bytes_soft=1_500,
    session_context_bytes_hard=2_200,
    recall_items=2,
    recall_word_budget=260,
    advisor_budget=1,
    max_stop_continuations=1,
    allow_prompt_improvement=True,
    allow_repeated_route_context=False,
    maintenance_mode="deferred",
)

TERRA = RuntimeProfile(
    name="terra",
    model_family="terra",
    prompt_context_bytes_soft=960,
    prompt_context_bytes_hard=1_400,
    session_context_bytes_soft=1_200,
    session_context_bytes_hard=1_800,
    recall_items=1,
    recall_word_budget=180,
    advisor_budget=0,
    max_stop_continuations=1,
    allow_prompt_improvement=False,
    allow_repeated_route_context=False,
    maintenance_mode="deferred",
)

SOL = RuntimeProfile(
    name="sol",
    model_family="sol",
    prompt_context_bytes_soft=450,
    prompt_context_bytes_hard=800,
    session_context_bytes_soft=500,
    session_context_bytes_hard=800,
    recall_items=1,
    recall_word_budget=120,
    advisor_budget=0,
    max_stop_continuations=1,
    allow_prompt_improvement=False,
    allow_repeated_route_context=False,
    maintenance_mode="deferred",
)

CONSERVATIVE_UNKNOWN = RuntimeProfile(
    name="conservative_unknown",
    model_family="unknown",
    prompt_context_bytes_soft=1_200,
    prompt_context_bytes_hard=2_200,
    session_context_bytes_soft=1_500,
    session_context_bytes_hard=2_200,
    recall_items=2,
    recall_word_budget=220,
    advisor_budget=1,
    max_stop_continuations=1,
    allow_prompt_improvement=True,
    allow_repeated_route_context=False,
    maintenance_mode="deferred",
)

_MODEL_KEYS = ("model", "model_name", "modelName", "model_id", "modelId")
_PROFILE_VALUES = {"auto", "luna", "terra", "sol", "conservative"}
_MODEL_TOKEN_RE = re.compile(r"[^a-z0-9.:-]+")


def _string_value(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def model_from_payload(payload: Mapping[str, object]) -> str:
    """Return only an explicit model field; transcript fields are excluded."""
    for key in _MODEL_KEYS:
        value = _string_value(payload.get(key))
        if value:
            return value
    for key in ("runtime", "context", "metadata", "agent", "subagent"):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            for model_key in _MODEL_KEYS:
                value = _string_value(nested.get(model_key))
                if value:
                    return value
    return ""


def _model_from_config() -> str:
    path = REPO_ROOT / ".codex" / "config.toml"
    try:
        with path.open("rb") as handle:
            config = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    return _string_value(config.get("model"))


def classify_model(model: str) -> str:
    normalized = model.lower().replace("_", "-").replace(" ", "-")
    if normalized == "sol" or "gpt-5.6-sol" in normalized or normalized.endswith("-sol"):
        return "sol"
    if normalized == "luna" or "gpt-5.6-luna" in normalized or normalized.endswith("-luna"):
        return "luna"
    if normalized == "terra" or "gpt-5.6-terra" in normalized or normalized.endswith("-terra"):
        return "terra"
    return "unknown"


def _profile_for_family(family: str) -> RuntimeProfile:
    if family == "luna":
        return LUNA
    if family == "sol":
        return SOL
    if family == "terra":
        return TERRA
    return CONSERVATIVE_UNKNOWN


def is_progress_maintenance(origin: object, intent: object) -> bool:
    """Recognize only the exact internal progress-maintenance contract."""
    return (
        _string_value(origin).lower() == IMPLEMENTATION_PROGRESS_ORIGIN
        and _string_value(intent).lower().replace("_", "-") == PROGRESS_MAINTENANCE_INTENT
    )


def progress_budget_for_provenance(provenance: ModelProvenance) -> ProgressBudget:
    """Select a bounded progress budget; unverified identity stays pointer-only."""
    if provenance.model_family == "luna" and provenance.model_verified:
        return ProgressBudget(512, 256, 1_024, 0)
    if provenance.model_family == "terra" and provenance.model_verified:
        return ProgressBudget(192, 192, 192, 0)
    return ProgressBudget(96, 96, 96, 0)


def model_provenance_from_payload(payload: Mapping[str, object]) -> ModelProvenance:
    """Resolve model evidence with payload > environment > repository precedence."""
    model = model_from_payload(payload)
    source = "payload" if model else ""
    if not model:
        model = _string_value(os.environ.get("RALPH_MODEL") or os.environ.get("CODEX_MODEL"))
        source = "environment" if model else ""
    if not model:
        model = _model_from_config()
        source = "repository-default" if model else "unknown"
    family = classify_model(model)
    if family not in MODEL_FAMILIES:
        family = "unknown"
    if source not in MODEL_SOURCES:
        source = "unknown"
    # Repository defaults are useful safety hints but cannot prove the active
    # per-turn selector. An unknown model is never verified.
    verified = source in {"payload", "environment"} and family != "unknown"
    return ModelProvenance(family, source, verified)


def profile_from_payload(payload: Mapping[str, object]) -> RuntimeProfile:
    """Resolve a safe profile with payload > explicit env > config precedence.

    ``RALPH_SCAFFOLD_PROFILE`` is intended for tests/diagnostics.  Invalid
    values and unknown models always select the conservative profile; no
    override can increase safety-sensitive permissions.
    """
    override = os.environ.get("RALPH_SCAFFOLD_PROFILE", "auto").strip().lower()
    provenance = model_provenance_from_payload(payload)
    if override not in _PROFILE_VALUES:
        template = CONSERVATIVE_UNKNOWN
    elif override in {"luna", "terra", "sol"}:
        # This is a safety-template override only; it must not rewrite the
        # model evidence used by progress cost policy.
        template = _profile_for_family(override)
    elif override == "conservative":
        template = CONSERVATIVE_UNKNOWN
    else:
        template = _profile_for_family(provenance.model_family)
    budget = progress_budget_for_provenance(provenance)
    return RuntimeProfile(
        **{
            **template.as_dict(),
            "model_family": provenance.model_family,
            "model_source": provenance.model_source,
            "model_verified": provenance.model_verified,
            "progress_recovery_bytes": budget.recovery_bytes,
            "progress_delta_bytes": budget.delta_bytes,
            "progress_expanded_bytes": budget.expanded_bytes,
            "progress_advisor_budget": budget.advisor_budget,
        }
    )


__all__ = [
    "CONSERVATIVE_UNKNOWN",
    "IMPLEMENTATION_PROGRESS_ORIGIN",
    "LUNA",
    "MODEL_FAMILIES",
    "MODEL_SOURCES",
    "PROGRESS_MAINTENANCE_INTENT",
    "PROGRESS_REASON_CODE",
    "ModelProvenance",
    "ProgressBudget",
    "TERRA",
    "SOL",
    "RuntimeProfile",
    "classify_model",
    "is_progress_maintenance",
    "model_from_payload",
    "model_provenance_from_payload",
    "progress_budget_for_provenance",
    "profile_from_payload",
]
