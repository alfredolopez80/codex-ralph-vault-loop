#!/usr/bin/env python3
from __future__ import annotations

from shared.paths import read_hook_input, write_json
from shared.sol_advisor import (
    has_fork_metadata,
    has_no_history_fork,
    is_sol_advisor,
    normalize_phase,
    read_state,
    reserve_sol_consultation,
)


def main() -> int:
    try:
        payload = read_hook_input()
        state = read_state(payload)
        routing = state.get("routing")
        if (
            is_sol_advisor(payload)
            and state.get("advisor_completed")
            and state.get("prior_verdict_fingerprint")
            and state.get("prior_verdict_fingerprint") == state.get("decision_fingerprint")
        ):
            write_json(
                {
                    "decision": "block",
                    "reason": "An equivalent Sol verdict is already complete; reuse it unless the evidence changes.",
                }
            )
            return 0
        if not state.get("final_review_eligible"):
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
            return 0
        if is_sol_advisor(payload) and isinstance(routing, dict) and routing.get("subagent_route") in {
            "sol-advisor",
            "sol-active-analysis",
        }:
            phase = normalize_phase(state.get("phase")) or "plan"
            reserved, reason = reserve_sol_consultation(
                payload,
                phase,
                str(routing.get("decision_fingerprint") or ""),
            )
            if not reserved:
                write_json({"decision": "block", "reason": reason})
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
