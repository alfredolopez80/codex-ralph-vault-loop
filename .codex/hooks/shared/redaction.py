from __future__ import annotations

import sys
from pathlib import Path


SECURITY_DIR = Path(__file__).resolve().parents[3] / "scripts" / "security"
if str(SECURITY_DIR) not in sys.path:
    sys.path.insert(0, str(SECURITY_DIR))

from sensitive_content import classify_text, redact_text as redact_sensitive_text  # noqa: E402


def redact_text(text: str) -> str:
    redacted, _changed = redact_sensitive_text(text)
    return redacted


def is_red(text: str) -> bool:
    return classify_text(text).classification == "RED"


def sensitivity_report(text: object) -> dict[str, object]:
    return classify_text(text).public_dict()


def safe_preview(value: object, limit: int = 1_000) -> str:
    text = redact_text(str(value))
    if len(text) > limit:
        return text[:limit].rstrip() + "...[truncated]"
    return text
