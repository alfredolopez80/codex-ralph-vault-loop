#!/usr/bin/env python3
from __future__ import annotations

import re

from shared.paths import read_hook_input, write_json


DESTRUCTIVE_PATTERNS = [
    re.compile(r"\brm\s+-rf\s+(/|~|\$HOME|\.)"),
    re.compile(r"\bgit\s+reset\s+--hard\b"),
    re.compile(r"\bgit\s+clean\s+-[a-zA-Z]*f"),
    re.compile(r"\bgit\s+push\b.*\s--force\b"),
    re.compile(r"\bchmod\s+-R\s+777\b"),
]


def command_from_payload(payload: dict) -> str:
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    if isinstance(tool_input, dict):
        return str(tool_input.get("command") or tool_input.get("cmd") or "")
    return str(tool_input)


def main() -> int:
    payload = read_hook_input()
    command = command_from_payload(payload)
    if not command:
        return 0

    for pattern in DESTRUCTIVE_PATTERNS:
        if pattern.search(command):
            write_json({"decision": "block", "reason": "Blocked obvious destructive command by pre_tool_guard."})
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
