#!/usr/bin/env python3
from __future__ import annotations

import io
import sys
import time
from contextlib import redirect_stdout

from shared.active_context import active_context_from_payload
from shared.paths import read_hook_input, write_json
from shared.sol_advisor import (
    has_fork_metadata,
    has_no_history_fork,
    is_sol_advisor,
    read_state,
)
from shared.runtime_observability import record_event


def _advisor_main(payload: dict | None = None) -> int:
    try:
        payload = payload if payload is not None else read_hook_input()
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
    except Exception:
        pass
    return 0


def main() -> int:
    started = time.perf_counter_ns()
    payload = read_hook_input()
    output = io.StringIO()
    with redirect_stdout(output):
        result = _advisor_main(payload)
    rendered = output.getvalue()
    if rendered:
        sys.stdout.write(rendered)
    try:
        record_event(
            active_context_from_payload(payload, resolve_git=False),
            payload,
            event="pre_tool",
            dispatcher="sol_advisor_pretool_guard",
            duration_ns=time.perf_counter_ns() - started,
            process_count=1,
            child_process_count=0,
            tool_family="agent" if "advisor" in str(payload.get("tool_name") or payload.get("tool") or "").lower() else "other",
            components_considered=["sol_advisor_eligibility"],
            components_executed=["deny" if rendered else "allow"],
            components_skipped=[],
            skipped_reason=[],
            output_bytes=len(rendered.encode("utf-8")),
            success=not rendered,
            advisor_count=1 if rendered else 0,
            scenario=payload.get("scenario"),
        )
    except Exception:
        pass
    return result


if __name__ == "__main__":
    raise SystemExit(main())
