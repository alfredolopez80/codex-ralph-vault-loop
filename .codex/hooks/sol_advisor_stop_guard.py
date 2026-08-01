#!/usr/bin/env python3
from __future__ import annotations

from shared.paths import read_hook_input
from shared.sol_advisor import mark_stop_guard, needs_stop_review, read_state


def main() -> int:
    try:
        payload = read_hook_input()
        if payload.get("stop_hook_active"):
            return 0
        state = read_state(payload)
        if not needs_stop_review(state):
            return 0
        # Stop is report-only for this policy.  Record the bounded
        # recommendation so Codex main can decide whether to spawn the
        # eligible advisor, but never block ordinary completion or create a
        # retry loop from a hook.
        mark_stop_guard(payload)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
