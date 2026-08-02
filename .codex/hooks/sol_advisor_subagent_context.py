#!/usr/bin/env python3
from __future__ import annotations

from shared.paths import read_hook_input, write_json
from shared.sol_advisor import advisor_context, is_sol_advisor, mark_advisor, read_state


def main() -> int:
    try:
        payload = read_hook_input()
        if not is_sol_advisor(payload):
            return 0
        state = read_state(payload)
        routing = state.get("routing")
        if not isinstance(routing, dict) or routing.get("subagent_route") not in {"sol-advisor", "sol-active-analysis"}:
            return 0
        state = mark_advisor(payload, completed=False, require_reservation=True)
        write_json({"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": advisor_context(state)}})
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
