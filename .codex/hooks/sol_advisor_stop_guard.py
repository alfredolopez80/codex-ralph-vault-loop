#!/usr/bin/env python3
from __future__ import annotations

from shared.paths import read_hook_input
from shared.sol_advisor import mark_stop_guard, read_state, stop_review_recommendation_pending


def run(payload: dict) -> bool:
    try:
        if payload.get("stop_hook_active"):
            return False
        state = read_state(payload)
        if not stop_review_recommendation_pending(state):
            return False
        # Stop is report-only for this policy. Record the bounded
        # recommendation so Codex main can decide whether to spawn the
        # eligible advisor; this hook never claims to enforce a final review.
        mark_stop_guard(payload)
        return True
    except Exception:
        return False


def main() -> int:
    run(read_hook_input())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
