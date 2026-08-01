#!/usr/bin/env python3
"""Validate a proposed native subagent spawn against the bounded route state."""
from __future__ import annotations

from typing import Any

from shared.paths import read_hook_input, write_json
from shared.sol_advisor import read_state


SUPPORTED_MODELS = {"gpt-5.6-terra", "gpt-5.6-sol"}
NO_HISTORY_VALUES = {"none", "fresh", "no-history", "no_history"}


def _sources(payload: dict[str, Any]) -> list[dict[str, Any]]:
    sources = [payload]
    for key in ("tool_input", "subagent", "agent"):
        value = payload.get(key)
        if isinstance(value, dict):
            sources.append(value)
    return sources


def _value(payload: dict[str, Any], *keys: str) -> object:
    for source in _sources(payload):
        for key in keys:
            value = source.get(key)
            if value is not None:
                return value
    return None


def _block(reason: str) -> None:
    write_json({"decision": "block", "reason": reason})


def main() -> int:
    normalized_tool = ""
    try:
        payload = read_hook_input()
        # This guard is only for the native subagent-spawn tool.  Other
        # tools may legitimately carry fields named ``model``, ``route``, or
        # ``task_name`` and must not be classified as a spawn attempt.
        tool_name = str(payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "")
        normalized_tool = tool_name.strip().lower().replace("-", "_")
        if normalized_tool not in {"spawn_agent", "spawnagent"}:
            return 0
        model = str(_value(payload, "model", "model_name", "modelName") or "").strip().lower()
        task_name = str(_value(payload, "task_name", "taskName") or "").strip().lower().replace("-", "_")
        route_requested = str(_value(payload, "subagent_route", "subagentRoute", "route") or "").strip().lower()
        if not (model in SUPPORTED_MODELS or task_name in {"sol_advisor", "sol_active_analysis", "terra_implementation"} or route_requested):
            return 0

        state = read_state(payload)
        routing = state.get("routing")
        if not isinstance(routing, dict):
            _block("Subagent routing state is missing; the spawn must be classified before it is created.")
            return 0
        if str(routing.get("sensitivity", "GREEN")).upper() == "RED":
            _block("RED-sensitive work remains local and cannot be delegated to a model subagent.")
            return 0

        expected_route = str(routing.get("subagent_route", "none"))
        expected_model = str(routing.get("subagent_model") or "")
        expected_effort = str(routing.get("subagent_effort") or "")
        expected_args = routing.get("spawn_arguments")
        if not isinstance(expected_args, dict) or not routing.get("spawn_required"):
            active_requested = route_requested == "sol-active-analysis" or task_name == "sol_active_analysis"
            if active_requested and str(routing.get("active_analysis_rejection_reason") or ""):
                _block(
                    "Active Sol analysis is not eligible: "
                    + str(routing.get("active_analysis_rejection_reason"))
                    + "."
                )
            else:
                _block("The proposed subagent route is not eligible for this bounded task decision.")
            return 0

        requested_route = route_requested
        if not requested_route:
            if task_name == "sol_advisor":
                # The native spawn schema has one Sol task name for both
                # advisor modes.  The persisted decision is the authoritative
                # discriminator when the caller sends the native payload
                # without a custom, unsupported route field.
                requested_route = (
                    expected_route
                    if expected_route in {"sol-advisor", "sol-active-analysis"}
                    else "sol-advisor"
                )
            elif task_name == "sol_active_analysis":
                requested_route = "sol-active-analysis"
            elif task_name == "terra_implementation":
                requested_route = "terra-implementation"
            elif model == "gpt-5.6-sol":
                requested_route = "sol-advisor"
            elif model == "gpt-5.6-terra":
                requested_route = "terra-implementation"
        if requested_route != expected_route:
            _block(f"Requested subagent route {requested_route or 'unknown'} does not match the classified route {expected_route}.")
            return 0

        requested_model = model
        requested_effort = str(_value(payload, "reasoning_effort", "reasoningEffort", "effort") or "").strip().lower()
        requested_task = task_name
        requested_fork = str(_value(payload, "fork_turns", "forkTurns", "history_mode", "historyMode") or "").strip().lower()
        if requested_model != expected_model:
            _block(f"Unsupported subagent model for this route: expected {expected_model or 'none'}.")
            return 0
        if requested_effort != expected_effort:
            _block(f"Unsupported subagent effort for this route: expected {expected_effort or 'none'}.")
            return 0
        expected_task = str(expected_args.get("task_name") or "")
        if expected_task and requested_task != expected_task:
            _block(f"Subagent task_name must be {expected_task}; do not substitute another lane.")
            return 0
        if requested_fork not in NO_HISTORY_VALUES:
            _block("Subagent spawn must use fork_turns=none so the full conversation history is not inherited.")
            return 0
    except Exception:
        # Ordinary tools remain fail-open, but once a native spawn has been
        # identified, a validation failure must fail closed at this trust
        # boundary instead of silently bypassing routing and RED controls.
        if normalized_tool in {"spawn_agent", "spawnagent"}:
            try:
                _block("Subagent routing validation failed; the spawn was blocked for safety.")
            except Exception:
                pass
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
