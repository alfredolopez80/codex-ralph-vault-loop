#!/usr/bin/env python3
from __future__ import annotations

from shared.paths import read_hook_input, write_json
from shared.sol_advisor import executor_context, initialize


def main() -> int:
    try:
        state = initialize(read_hook_input())
        context = executor_context(state or {})
        if context:
            write_json({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}})
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
