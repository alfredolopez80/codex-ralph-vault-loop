#!/usr/bin/env python3
from __future__ import annotations

from shared.paths import read_hook_input, write_json
from shared.sol_advisor import mark_stop_guard, needs_stop_review, read_state


def main() -> int:
    try:
        payload = read_hook_input()
        if payload.get("stop_hook_active"):
            return 0
        state = read_state(payload)
        if not needs_stop_review(state):
            return 0
        mark_stop_guard(payload)
        write_json(
            {
                "decision": "block",
                "reason": "High-impact task requires a completed native sol-advisor consultation before completion.",
            }
        )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
