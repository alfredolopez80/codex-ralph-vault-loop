from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TextIO

try:
    from .sensitive_content import classify_text
except ImportError:  # pragma: no cover - used when scripts/security is on sys.path.
    from sensitive_content import classify_text


MASK = "[REDACTED:diagnostic]"


def clean_value(value: Any) -> Any:
    if isinstance(value, str):
        report = classify_text(value)
        return MASK if report.changed or report.classification == "RED" else value
    if isinstance(value, dict):
        return {str(key): clean_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean_value(item) for item in value]
    if isinstance(value, tuple):
        return [clean_value(item) for item in value]
    return value


def safe_json_text(payload: dict[str, Any]) -> str:
    return json.dumps(clean_value(payload), indent=2, sort_keys=True)


def safe_jsonl_text(payload: dict[str, Any]) -> str:
    return json.dumps(clean_value(payload), sort_keys=True)


def write_json(path: Path, payload: dict[str, Any], *, create_parent: bool = False) -> None:
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(safe_json_text(payload) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(safe_jsonl_text(payload) + "\n")


def emit_json(payload: dict[str, Any], *, stream: TextIO | None = None) -> None:
    (stream or sys.stdout).write(safe_json_text(payload) + "\n")
