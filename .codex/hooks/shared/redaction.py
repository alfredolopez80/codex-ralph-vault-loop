from __future__ import annotations

import re


SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|credential)\s*[:=]\s*['\"]?[^'\"\s]+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
]


RED_MARKERS = (
    "api_key",
    "private key",
    "secret=",
    "password=",
    "token=",
    "credential",
    "wallet",
)


def redact_text(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def is_red(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in RED_MARKERS)


def safe_preview(value: object, limit: int = 1_000) -> str:
    text = redact_text(str(value))
    if len(text) > limit:
        return text[:limit].rstrip() + "...[truncated]"
    return text
