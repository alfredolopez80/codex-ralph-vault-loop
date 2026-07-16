#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from typing import Any


MAX_OUTPUT_BYTES = 768
ADDITIONAL_CONTEXT = (
    "Improve Prompt Contract: internally frame every non-empty request while preserving its task type, user values, "
    "language, format, scope, and authorization. Infer goal, done evidence, constraints and permissions, relevant "
    "prerequisites and tools, output, and stop rules only where they change behavior. Never expand scope or authority. "
    "Answer, review, diagnosis, and planning requests do not authorize changes. Keep trivial work lightweight. "
    "Do not show, quote, or rewrite the user prompt unless the user asks for one."
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
