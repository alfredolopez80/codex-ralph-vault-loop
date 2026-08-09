#!/usr/bin/env python3
from __future__ import annotations

import json
import time

from shared.active_context import active_context_from_payload
from shared.paths import read_hook_input, write_json
from shared.sol_advisor import advisor_context, is_sol_advisor, mark_advisor, read_state
from shared.runtime_observability import record_event


def main() -> int:
    started = time.perf_counter_ns()
    payload = read_hook_input()
    emitted = False
    emitted_bytes = 0
    try:
        if not is_sol_advisor(payload):
            return 0
        state = read_state(payload)
        routing = state.get("routing")
        if not isinstance(routing, dict) or routing.get("subagent_route") not in {"sol-advisor", "sol-active-analysis"}:
            return 0
        state = mark_advisor(payload, completed=False, require_reservation=True)
        context = advisor_context(state)
        rendered = {"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": context}}
        emitted_bytes = len(json.dumps(rendered, ensure_ascii=True).encode("utf-8"))
        write_json(rendered)
        emitted = True
    except Exception:
        pass
    try:
        record_event(
            active_context_from_payload(payload, resolve_git=False),
            payload,
            event="subagent",
            dispatcher="sol_advisor_subagent_context",
            duration_ns=time.perf_counter_ns() - started,
            process_count=1,
            child_process_count=0,
            components_considered=["advisor_context"],
            components_executed=["advisor_context"] if emitted else [],
            components_skipped=[] if emitted else ["not_eligible"],
            skipped_reason=[] if emitted else ["not_advisor"],
            output_bytes=emitted_bytes,
            advisor_count=1 if emitted else 0,
            success=True,
        )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
