#!/usr/bin/env python3
from __future__ import annotations

import io
import sys
import time
from contextlib import redirect_stdout

from shared.active_context import active_context_from_payload
from shared.paths import read_hook_input, write_json
from shared.sol_advisor import (
    has_no_history_fork,
    is_sol_advisor,
    read_state,
)
from shared.runtime_observability import record_event
from shared.runtime_profile import PROGRESS_REASON_CODE, is_progress_maintenance


def _native_spawn(payload: dict) -> bool:
    value = str(payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "")
    normalized = value.strip().lower().replace("-", "_").rsplit(".", 1)[-1]
    return normalized.rsplit("__", 1)[-1] in {"spawn_agent", "spawnagent"}


def _field(payload: dict, *keys: str) -> object:
    for source in (payload, payload.get("tool_input"), payload.get("toolInput"), payload.get("input")):
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if value is not None and value != "":
                return value
    return None


def _advisor_main(payload: dict | None = None) -> int:
    try:
        payload = payload if payload is not None else read_hook_input()
        if not _native_spawn(payload):
            return 0
        if is_progress_maintenance(
            _field(payload, "origin", "task_origin", "taskOrigin"),
            _field(payload, "intent", "task_type", "taskType"),
        ):
            write_json({"decision": "block", "reason": PROGRESS_REASON_CODE})
            return 0
        state = read_state(payload)
        routing = state.get("routing")
        if is_progress_maintenance(
            _field(payload, "origin", "task_origin", "taskOrigin")
            or state.get("origin")
            or (routing.get("origin") if isinstance(routing, dict) else None),
            _field(payload, "intent", "task_type", "taskType")
            or state.get("intent")
            or (routing.get("intent") if isinstance(routing, dict) else None),
        ):
            write_json({"decision": "block", "reason": PROGRESS_REASON_CODE})
            return 0
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
        if is_sol_advisor(payload) and not has_no_history_fork(payload):
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
