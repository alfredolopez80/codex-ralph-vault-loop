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


def parse_input() -> dict[str, Any] | None:
    try:
        stream = getattr(sys.stdin, "buffer", sys.stdin)
        value = stream.read(MAX_INPUT_BYTES + 1)
        raw = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
        if len(raw.encode("utf-8")) > MAX_INPUT_BYTES:
            sys.stderr.write("security_pre_tool_dispatch input exceeded its bounded limit; action unknown and allowed.\n")
            return None
        value = json.loads(raw) if raw.strip() else {}
    except (OSError, json.JSONDecodeError):
        sys.stderr.write("security_pre_tool_dispatch invalid JSON; action unknown and allowed.\n")
        return None
    if not isinstance(value, dict):
        sys.stderr.write("security_pre_tool_dispatch payload is not an object; action unknown and allowed.\n")
        return None
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
    payload = parse_input()
    if payload is None:
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
