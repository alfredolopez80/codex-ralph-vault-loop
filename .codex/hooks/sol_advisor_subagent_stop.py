#!/usr/bin/env python3
from __future__ import annotations

from shared.paths import read_hook_input
from shared.sol_advisor import has_completion_evidence, is_sol_advisor, mark_advisor, read_state


def main() -> int:
    try:
        payload = read_hook_input()
        routing = read_state(payload).get("routing")
        if (
            is_sol_advisor(payload)
            and isinstance(routing, dict)
            and routing.get("subagent_route") in {"sol-advisor", "sol-active-analysis"}
            and has_completion_evidence(payload)
        ):
            mark_advisor(payload, completed=True)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
