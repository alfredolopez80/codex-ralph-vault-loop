"""Conservative, payload-first runtime profiles for hook context budgets.

The profile is deliberately small and side-effect free.  It never inspects a
transcript: model identity comes from the hook payload and only falls back to
an explicit environment value or the repository config.
"""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .paths import REPO_ROOT


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

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


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
_PROFILE_VALUES = {"auto", "luna", "sol", "conservative"}
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
    if "gpt-5.6-sol" in normalized or normalized.endswith("-sol"):
        return "sol"
    if "gpt-5.6-luna" in normalized or normalized.endswith("-luna"):
        return "luna"
    return "unknown"


def _profile_for_family(family: str) -> RuntimeProfile:
    if family == "luna":
        return LUNA
    if family == "sol":
        return SOL
    return CONSERVATIVE_UNKNOWN


def profile_from_payload(payload: Mapping[str, object]) -> RuntimeProfile:
    """Resolve a safe profile with payload > explicit env > config precedence.

    ``RALPH_SCAFFOLD_PROFILE`` is intended for tests/diagnostics.  Invalid
    values and unknown models always select the conservative profile; no
    override can increase safety-sensitive permissions.
    """
    override = os.environ.get("RALPH_SCAFFOLD_PROFILE", "auto").strip().lower()
    if override not in _PROFILE_VALUES:
        return CONSERVATIVE_UNKNOWN
    if override in {"luna", "sol"}:
        return _profile_for_family(override)
    if override == "conservative":
        return CONSERVATIVE_UNKNOWN

    model = model_from_payload(payload)
    if not model:
        model = _string_value(os.environ.get("RALPH_MODEL") or os.environ.get("CODEX_MODEL"))
    if not model:
        model = _model_from_config()
    return _profile_for_family(classify_model(model))


__all__ = [
    "CONSERVATIVE_UNKNOWN",
    "LUNA",
    "SOL",
    "RuntimeProfile",
    "classify_model",
    "model_from_payload",
    "profile_from_payload",
]
