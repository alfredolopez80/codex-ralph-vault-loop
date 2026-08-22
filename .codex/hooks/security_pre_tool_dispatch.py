#!/usr/bin/env python3
"""Narrow deny-first PreToolUse security plane.

Only independent safety controls run here. Lifecycle, continuity, routing,
advisor eligibility, leases, activation, and memory state are intentionally
absent from this dispatcher.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from pre_tool_guard import security_only_denial
from shared.security_boundary import deny, external_denial, tool_name, workspace_denial

MAX_INPUT_BYTES = 4 * 1024 * 1024


class InputContractError(ValueError):
    """Raised when the security dispatcher cannot validate its input."""


def parse_input() -> dict[str, Any]:
    try:
        stream = getattr(sys.stdin, "buffer", sys.stdin)
        value = stream.read(MAX_INPUT_BYTES + 1)
    except OSError as exc:
        raise InputContractError("Security validation could not read the tool request; retry the action.") from exc

    if isinstance(value, bytes):
        if len(value) > MAX_INPUT_BYTES:
            raise InputContractError(
                "Security validation rejected an oversized tool request; retry with a bounded input."
            )
        try:
            raw = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InputContractError("Security validation received malformed hook input; retry the action.") from exc
    else:
        raw = str(value)
        if len(raw.encode("utf-8")) > MAX_INPUT_BYTES:
            raise InputContractError(
                "Security validation rejected an oversized tool request; retry with a bounded input."
            )

    try:
        value = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        raise InputContractError("Security validation received malformed hook input; retry the action.") from exc
    if not isinstance(value, dict):
        raise InputContractError("Security validation requires an object-shaped tool request; retry the action.")
    return value


def dispatch(payload: dict[str, Any]) -> dict[str, str] | None:
    tool = tool_name(payload)
    if not tool:
        return None

    safety = security_only_denial(payload)
    if safety:
        return deny(safety.get("reason"))

    egress = external_denial(payload)
    if egress:
        return egress

    return workspace_denial(payload, tool)


def main() -> int:
    try:
        payload = parse_input()
    except InputContractError as exc:
        sys.stdout.write(json.dumps(deny(str(exc)), ensure_ascii=True, separators=(",", ":")) + "\n")
        return 0
    try:
        response = dispatch(payload)
    except Exception:
        response = deny("Security validation failed for the identified action.") if tool_name(payload) else None
    if response:
        sys.stdout.write(json.dumps(response, ensure_ascii=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
