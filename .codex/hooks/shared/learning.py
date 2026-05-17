from __future__ import annotations

import re
import unicodedata
from typing import Iterable

from .redaction import is_red, safe_preview


LEARNING_KEYWORDS = (
    "learned",
    "aprendido",
    "aprendizaje",
    "decision",
    "fixed",
    "corregido",
    "root cause",
    "causa raiz",
    "checkpoint",
    "validated",
    "validado",
    "pass",
    "passed",
    "paso",
    "failed",
    "fallo",
    "blocker",
    "bloqueador",
    "resultado",
    "conclusion",
)

SECTION_HEADERS = (
    "conclusion",
    "root cause",
    "causa raiz",
    "decision",
    "result",
    "resultado",
    "validation",
    "validacion",
)


def normalize_learning_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower()


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    escaped = re.escape(keyword)
    escaped = escaped.replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![a-z0-9_]){escaped}(?![a-z0-9_])")


def _section_pattern(headers: Iterable[str]) -> re.Pattern[str]:
    body = "|".join(re.escape(header).replace(r"\ ", r"\s+") for header in headers)
    return re.compile(rf"(?im)^\s*(?:{body})\s*:")


KEYWORD_PATTERNS = tuple(_keyword_pattern(keyword) for keyword in LEARNING_KEYWORDS)
SECTION_PATTERN = _section_pattern(SECTION_HEADERS)


def should_persist_learning(text: str) -> bool:
    if not text.strip():
        return False
    normalized = normalize_learning_text(text)
    if SECTION_PATTERN.search(normalized):
        return True
    return any(pattern.search(normalized) for pattern in KEYWORD_PATTERNS)


def learning_text_from_payload(payload: dict, fields: tuple[str, ...]) -> str | None:
    raw_parts = [str(payload.get(field, "")) for field in fields if payload.get(field)]
    raw_text = " ".join(raw_parts)
    if not raw_text.strip() or is_red(raw_text):
        return None
    text = " ".join(safe_preview(payload.get(field, "")) for field in fields if payload.get(field))
    if should_persist_learning(text):
        return text
    return None
