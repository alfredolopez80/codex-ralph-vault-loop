#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from typing import Any

MAX_OUTPUT_BYTES = 768
ADDITIONAL_CONTEXT = (
    "Prompt contract: preserve task type, language, format, scope, and authority. Infer goal, evidence, constraints, "
    "tools, and stop rules only when they change behavior. Do not expand scope or authority: answering, reviewing, "
    "diagnosing, and planning authorize no changes. Keep trivial work light. Never quote or rewrite the prompt "
    "unless asked."
)


def has_prompt(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    return any(isinstance(payload.get(key), str) and payload[key].strip() for key in ("prompt", "user_prompt"))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not has_prompt(payload):
            return 0
        output = json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": ADDITIONAL_CONTEXT,
                }
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        if len(output.encode("utf-8")) > MAX_OUTPUT_BYTES:
            return 0
        sys.stdout.write(output + "\n")
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
