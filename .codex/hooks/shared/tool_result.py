"""Normalize tool outcomes shared by checkpoint and advisory hooks."""
from __future__ import annotations

from typing import Any

RESULT_CODE_KEYS = ("exit_code", "returncode", "return_code")
NESTED_RESULT_KEYS = ("tool_response", "toolResponse")


def _success_from_mapping(value: object) -> bool | None:
    if not isinstance(value, dict):
        return None
    explicit = value.get("success")
    if isinstance(explicit, bool):
        return explicit
    for key in RESULT_CODE_KEYS:
        code = value.get(key)
        if isinstance(code, int) and not isinstance(code, bool):
            return code == 0
    return None


def success_from_payload(payload: dict[str, Any]) -> bool | None:
    """Return the canonical tool outcome, or None when it is inconclusive.

    Codex payloads may expose the outcome at the top level or in the native
    ``tool_response`` object. An explicit boolean takes precedence over an
    exit code at the same level; top-level evidence takes precedence over the
    nested response. Unknown or malformed values remain inconclusive.
    """
    result = _success_from_mapping(payload)
    if result is not None:
        return result
    for key in NESTED_RESULT_KEYS:
        result = _success_from_mapping(payload.get(key))
        if result is not None:
            return result
    return None
