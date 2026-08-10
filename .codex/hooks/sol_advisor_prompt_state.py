#!/usr/bin/env python3
from __future__ import annotations

from shared.paths import read_hook_input, write_json
from shared.sol_advisor import executor_context, initialize


def routing_context(state: dict[str, object]) -> str:
    routing = state.get("routing")
    if not isinstance(routing, dict):
        return ""
    fields = (
        "policy_version",
        "raw_complexity",
        "effective_complexity",
        "origin",
        "intent",
        "sensitivity",
        "configured_executor_model",
        "configured_executor_effort",
        "subagent_route",
        "subagent_model",
        "subagent_mode",
        "subagent_effort",
        "spawn_required",
        "reason_code",
        "budget_remaining",
        "worker_budget",
        "advisor_budget",
    )
    aliases = {"raw_complexity": "raw", "effective_complexity": "effective"}
    if routing.get("subagent_route") == "none":
        aliases["subagent_route"] = "lane"
    values = " ".join(f"{aliases.get(field, field)}={routing.get(field)}" for field in fields)
    return f"ROUTE_DECISION {values}. Configured executor remains unchanged; this is subagent routing metadata only."


def main() -> int:
    try:
        state = initialize(read_hook_input())
        if not state:
            return 0
        route = routing_context(state)
        context = executor_context(state)
        context = f"{route} {context}".strip()
        if context:
            write_json({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}})
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
