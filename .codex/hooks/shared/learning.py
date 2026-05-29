from __future__ import annotations

import re
import unicodedata
from typing import Iterable

from .redaction import is_red, safe_preview
from .context_budget import text_is_toxic


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
    "fact",
    "validated fact",
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


def payload_indicates_failure(payload: dict) -> bool:
    explicit_success = any(key in payload and payload.get(key) is True for key in ("success", "ok", "passed"))
    for key in ("success", "ok", "passed"):
        if key in payload and payload.get(key) is False:
            return True
    for key in ("status", "outcome", "result_status"):
        value = str(payload.get(key, "")).strip().lower()
        if value in {"failed", "failure", "error", "errored", "timeout", "cancelled", "canceled"}:
            return True
    for key in ("returncode", "exit_code", "exitCode"):
        value = payload.get(key)
        if isinstance(value, int) and value != 0:
            return True
    return bool(payload.get("error") or (payload.get("stderr") and not explicit_success))


def extract_validated_learning(text: str) -> str | None:
    if not text.strip() or is_red(text) or text_is_toxic(text):
        return None
    preview = safe_preview(text, limit=2_000).strip()
    if not should_persist_learning(preview):
        return None

    lines = [line.strip() for line in preview.splitlines() if line.strip()]
    if len(lines) <= 1:
        return preview

    validated: list[str] = []
    for line in lines:
        normalized = normalize_learning_text(line)
        if SECTION_PATTERN.search(normalized):
            validated.append(line)
        elif any(marker in normalized for marker in ("validated", "validado", "pass", "passed", "paso")) and any(
            marker in normalized for marker in ("decision", "fact", "root cause", "causa raiz", "conclusion", "resultado")
        ):
            validated.append(line)
    if not validated:
        return None
    return "\n".join(validated)


def learning_text_from_payload(payload: dict, fields: tuple[str, ...]) -> str | None:
    if payload_indicates_failure(payload):
        return None
    raw_parts = [str(payload.get(field, "")) for field in fields if payload.get(field)]
    raw_text = " ".join(raw_parts)
    return extract_validated_learning(raw_text)
