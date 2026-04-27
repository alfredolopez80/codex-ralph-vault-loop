from __future__ import annotations

import sys
from pathlib import Path

from _memory_common import normalize_classification


SECURITY_DIR = Path(__file__).resolve().parents[1] / "security"
if str(SECURITY_DIR) not in sys.path:
    sys.path.insert(0, str(SECURITY_DIR))

from sensitive_content import classify_text  # noqa: E402

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
        normalize_classification(requested)
    report = classify_text(text, requested)
    if report.classification == "RED":
        return "RED"
    if requested:
        return report.classification
    lowered = text.lower()
    if any(marker in lowered for marker in RED_MARKERS):
        return "RED"
    if any(marker in lowered for marker in YELLOW_MARKERS):
        return "YELLOW"
    return "GREEN"
