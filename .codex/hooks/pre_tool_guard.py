#!/usr/bin/env python3
from __future__ import annotations

import re

from shared.paths import read_hook_input, write_json
from shared.redaction import is_red, sensitivity_report


DESTRUCTIVE_PATTERNS = [
    re.compile(r"\brm\s+-rf\s+(/|~|\$HOME|\.)"),
    re.compile(r"\bgit\s+reset\s+--hard\b"),
    re.compile(r"\bgit\s+clean\s+-[a-zA-Z]*f"),
    re.compile(r"\bgit\s+push\b.*\s--force\b"),
    re.compile(r"\bchmod\s+-R\s+777\b"),
]

SENSITIVE_COMMAND_PATTERNS = [
    re.compile(
        r"(?i)\b(cat|less|more|head|tail|sed|awk|pbcopy|open|curl|wget|scp|rsync)\b"
        r".*(\.env|id_rsa|id_ed25519|\.pem|\.key|wallet|credential|secret|token)"
    ),
    re.compile(r"(?i)\b(echo|printf|curl|wget|npx|node|python3?)\b.*(api[_-]?key|secret|token|password|credential)"),
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
    for pattern in SENSITIVE_COMMAND_PATTERNS:
        if pattern.search(command):
            write_json({"decision": "block", "reason": "Blocked command that could expose RED-sensitive material."})
            return 0
    if is_red(command):
        report = sensitivity_report(command)
        finding_labels = [item["label"] for item in report.get("findings", []) if isinstance(item, dict)]
        write_json(
            {
                "decision": "block",
                "reason": "Blocked command containing RED-sensitive material.",
                "findings": finding_labels,
            }
        )
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
