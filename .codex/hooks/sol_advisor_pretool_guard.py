#!/usr/bin/env python3
from __future__ import annotations

from shared.paths import read_hook_input, write_json
from shared.sol_advisor import has_fork_metadata, has_no_history_fork, is_sol_advisor, read_state


def main() -> int:
    try:
        payload = read_hook_input()
        state = read_state(payload)
        if not state.get("final_review_eligible") or state.get("advisor_completed"):
            return 0
        # Codex currently omits fork metadata from some PreToolUse payloads.
        # Reject an explicit inherited fork, but let the native instruction
        # contract carry a missing field rather than suppressing Sol entirely.
        if is_sol_advisor(payload) and has_fork_metadata(payload) and not has_no_history_fork(payload):
            write_json(
                {
                    "decision": "block",
                    "reason": "Invoke sol-advisor with a fresh no-history fork and include the compact decision brief.",
                }
            )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
