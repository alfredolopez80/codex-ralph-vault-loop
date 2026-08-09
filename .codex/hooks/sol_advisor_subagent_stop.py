#!/usr/bin/env python3
from __future__ import annotations

import time

from shared.active_context import active_context_from_payload
from shared.paths import read_hook_input
from shared.sol_advisor import (
    has_completion_evidence,
    is_sol_advisor,
    mark_advisor,
    read_state,
)
from shared.runtime_observability import record_event


def main() -> int:
    started = time.perf_counter_ns()
    payload = read_hook_input()
    completed = False
    try:
        routing = read_state(payload).get("routing")
        if (
            is_sol_advisor(payload)
            and isinstance(routing, dict)
            and routing.get("subagent_route") in {"sol-advisor", "sol-active-analysis"}
            and has_completion_evidence(payload)
        ):
            mark_advisor(payload, completed=True, require_completion_match=True)
            completed = True
    except Exception:
        pass
    try:
        record_event(
            active_context_from_payload(payload, resolve_git=False),
            payload,
            event="subagent",
            dispatcher="sol_advisor_subagent_stop",
            duration_ns=time.perf_counter_ns() - started,
            process_count=1,
            child_process_count=0,
            components_considered=["advisor_completion"],
            components_executed=["advisor_completion"] if completed else [],
            components_skipped=[] if completed else ["not_complete"],
            skipped_reason=[] if completed else ["no_completion_evidence"],
            advisor_count=1 if completed else 0,
            success=completed,
        )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
