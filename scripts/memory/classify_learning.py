from __future__ import annotations

from _memory_common import normalize_classification


RED_MARKERS = (
    "api_key",
    "private key",
    "secret=",
    "password=",
    "token=",
    "credential",
    "wallet",
)

YELLOW_MARKERS = (
    "project",
    "repo",
    "local",
    "migration",
    "checkpoint",
    "handoff",
)


def classify_learning(text: str, requested: str | None = None) -> str:
    if requested:
        return normalize_classification(requested)
    lowered = text.lower()
    if any(marker in lowered for marker in RED_MARKERS):
        return "RED"
    if any(marker in lowered for marker in YELLOW_MARKERS):
        return "YELLOW"
    return "GREEN"
