#!/usr/bin/env python3
"""Validate a proposed native subagent spawn against the bounded route state."""
from __future__ import annotations

from typing import Any

from shared.paths import read_hook_input, write_json
from shared.redaction import is_red
from shared.sol_advisor import normalize_phase, read_state, reserve_sol_consultation


SUPPORTED_MODELS = {"gpt-5.6-terra", "gpt-5.6-sol"}
MANAGED_ROUTES = {"terra-implementation", "sol-advisor", "sol-active-analysis"}
MANAGED_TASK_NAMES = {"terra_implementation", "sol_advisor", "sol_active_analysis"}
MANAGED_AGENT_TYPES = {"sol-advisor"}
NO_HISTORY_VALUES = {"none", "fresh", "no-history", "no_history"}
BRIEF_KEYS = ("message", "prompt", "brief", "decision_brief", "decisionBrief")
NATIVE_BRIEF_KEYS = ("message", "prompt", "brief", "decision_brief", "decisionBrief")
MAX_BRIEF_CHARS = 8_000


def _sources(payload: dict[str, Any]) -> list[dict[str, Any]]:
    sources = [payload]
    for key in ("tool_input", "toolInput", "input", "subagent", "agent"):
        value = payload.get(key)
        if isinstance(value, dict):
            sources.append(value)
    return sources


def _value(payload: dict[str, Any], *keys: str) -> object:
    candidates: list[tuple[str, object]] = []
    seen_sources: set[int] = set()
    for source in _sources(payload):
        if id(source) in seen_sources:
            continue
        seen_sources.add(id(source))
        for key in keys:
            value = source.get(key)
            if value is not None:
                candidates.append((key, value))
    if not candidates:
        return None

    def canonical(value: object) -> str:
        text = str(value).strip().lower()
        # Native aliases commonly differ only in separator style.
        return text.replace("_", "-")

    normalized = {canonical(value) for _key, value in candidates}
    if len(normalized) > 1:
        aliases = ", ".join(sorted({key for key, _value in candidates}))
        raise ValueError(f"conflicting native spawn aliases: {aliases}")
    return candidates[0][1]


def _brief_values(payload: dict[str, Any]) -> list[str]:
    """Collect all bounded free-text spawn briefs across native payload sources."""
    values: list[str] = []
    for source in _sources(payload):
        for key in BRIEF_KEYS:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value)
    return values


def _native_brief_values(payload: dict[str, Any]) -> list[str]:
    """Return spawn-owned brief fields, excluding the parent prompt envelope."""
    values: list[str] = []
    for index, source in enumerate(_sources(payload)):
        for key in NATIVE_BRIEF_KEYS:
            if index == 0 and key == "prompt":
                continue
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value)
    return values


def _phase(state: dict[str, Any]) -> str:
    """Resolve the lifecycle phase from persisted state, never caller input."""
    value = str(state.get("phase") or "plan").strip().lower().replace("_", "-")
    return {
        "initial": "plan",
        "planning": "plan",
        "start": "plan",
        "failure": "stuck",
        "debug": "stuck",
        "blocked": "stuck",
        "completion": "final",
        "stop": "final",
        "review": "final",
    }.get(value, value)


def _block(reason: str) -> None:
    write_json({"decision": "block", "reason": reason})


def _is_managed_spawn(
    *, model: str, task_name: str, route_requested: str, agent_type: str
) -> bool:
    """Return whether this spawn belongs to the Terra/Sol policy boundary."""
    return bool(
        model in SUPPORTED_MODELS
        or task_name in MANAGED_TASK_NAMES
        or route_requested in MANAGED_ROUTES
        or agent_type in MANAGED_AGENT_TYPES
    )


def _live_budget_remaining(state: dict[str, Any]) -> int:
    """Return the conservative live Sol allowance, or zero if malformed."""
    try:
        consultation_budget = int(state["consultation_budget"])
        consultation_count = int(state["consultation_count"])
        stored_remaining = int(state["budget_remaining"])
    except (KeyError, TypeError, ValueError):
        return 0
    if consultation_budget < 0 or consultation_count < 0 or stored_remaining < 0:
        return 0
    if consultation_count > consultation_budget:
        return 0
    return max(0, min(stored_remaining, consultation_budget - consultation_count))


def main() -> int:
    normalized_tool = ""
    native_tool = ""
    managed_spawn = False
    try:
        payload = read_hook_input()
        # This guard is only for the native subagent-spawn tool.  Other
        # tools may legitimately carry fields named ``model``, ``route``, or
        # ``task_name`` and must not be classified as a spawn attempt.
        tool_name = str(payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "")
        normalized_tool = tool_name.strip().lower().replace("-", "_")
        # Codex may report a namespaced tool identifier such as
        # ``collaboration.spawn_agent``. The final component is the native
        # tool identity; ignoring the namespace would bypass this guard.
        native_tool = normalized_tool.rsplit(".", 1)[-1]
        if native_tool not in {"spawn_agent", "spawnagent"}:
            return 0
        model = str(_value(payload, "model", "model_name", "modelName") or "").strip().lower()
        task_name = str(_value(payload, "task_name", "taskName") or "").strip().lower().replace("-", "_")
        route_requested = str(_value(payload, "subagent_route", "subagentRoute") or "").strip().lower()
        requested_agent_type = (
            str(_value(payload, "agent_type", "agentType") or "")
            .strip()
            .lower()
            .replace("_", "-")
        )
        managed_spawn = _is_managed_spawn(
            model=model,
            task_name=task_name,
            route_requested=route_requested,
            agent_type=requested_agent_type,
        )

        # RED content must not escape through any native spawn profile. Scan
        # every source before the managed-lane early return; a benign
        # top-level field must not mask a sensitive nested tool brief.
        briefs = _brief_values(payload)
        if any(is_red(brief) for brief in briefs):
            _block("RED-sensitive subagent brief remains local and cannot be delegated.")
            return 0

        requested_fork = str(_value(payload, "fork_turns", "forkTurns", "history_mode", "historyMode") or "").strip().lower()
        state = read_state(payload)
        routing = state.get("routing")
        persisted_sensitivity = str(state.get("sensitivity", "GREEN")).strip().upper()
        if isinstance(routing, dict):
            persisted_sensitivity = max(
                (persisted_sensitivity, str(routing.get("sensitivity", "GREEN")).strip().upper()),
                key=lambda value: {"GREEN": 0, "YELLOW": 1, "RED": 2}.get(value, 0),
            )
        if persisted_sensitivity == "RED":
            _block("RED-sensitive task state remains local and cannot be delegated to a native subagent.")
            return 0
        if not managed_spawn:
            # A prompt-level classification cannot prove that later assistant
            # or tool output is safe to inherit. Generic/native profiles must
            # therefore use an explicit fresh fork with a bounded brief;
            # managed profiles receive the same check below after route
            # validation. This keeps full conversation history local even when
            # the current task state is GREEN or YELLOW.
            native_briefs = list(dict.fromkeys(_native_brief_values(payload)))
            if sum(len(brief) for brief in native_briefs) > MAX_BRIEF_CHARS:
                _block("Subagent brief exceeds the bounded context limit; do not forward full history.")
                return 0
            if not native_briefs:
                _block("Native subagent spawn requires a non-empty bounded decision brief.")
                return 0
            if requested_fork not in NO_HISTORY_VALUES:
                _block("Native spawns that inherit history require fork_turns=none and a bounded brief.")
                return 0
            return 0
        if not isinstance(routing, dict):
            _block("Subagent routing state is missing; the spawn must be classified before it is created.")
            return 0
        if str(routing.get("sensitivity", "GREEN")).upper() == "RED":
            _block("RED-sensitive work remains local and cannot be delegated to a model subagent.")
            return 0
        native_briefs = list(dict.fromkeys(_native_brief_values(payload)))
        if sum(len(brief) for brief in native_briefs) > MAX_BRIEF_CHARS:
            _block("Subagent brief exceeds the bounded context limit; do not forward full history.")
            return 0
        if not native_briefs:
            _block("Managed subagent spawn requires a non-empty bounded decision brief.")
            return 0

        expected_route = str(routing.get("subagent_route", "none"))
        expected_model = str(routing.get("subagent_model") or "")
        expected_effort = str(routing.get("subagent_effort") or "")
        expected_args = routing.get("spawn_arguments")
        if expected_route in {"sol-advisor", "sol-active-analysis"} and _live_budget_remaining(state) <= 0:
            _block("Sol consultation budget is exhausted; do not create another advisor spawn.")
            return 0
        if (
            expected_route in {"sol-advisor", "sol-active-analysis"}
            and state.get("advisor_completed")
            and state.get("prior_verdict_fingerprint")
            and state.get("prior_verdict_fingerprint") == state.get("decision_fingerprint")
        ):
            _block("An equivalent Sol verdict is already complete; reuse it unless the evidence changes.")
            return 0
        if expected_route in {"sol-advisor", "sol-active-analysis"}:
            phase = _phase(state)
            consulted_phases = state.get("consulted_phases")
            if isinstance(consulted_phases, dict) and consulted_phases.get(phase):
                _block("A Sol consultation has already been started for this lifecycle phase.")
                return 0
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
        if requested_model != expected_model:
            _block(f"Unsupported subagent model for this route: expected {expected_model or 'none'}.")
            return 0
        if requested_effort != expected_effort:
            _block(f"Unsupported subagent effort for this route: expected {expected_effort or 'none'}.")
            return 0
        expected_agent_type = str(expected_args.get("agent_type") or "").strip().lower().replace("_", "-")
        if expected_agent_type and requested_agent_type != expected_agent_type:
            _block(f"Subagent agent_type must be {expected_agent_type}; do not substitute another profile.")
            return 0
        expected_task = str(expected_args.get("task_name") or "")
        if expected_task and requested_task != expected_task:
            _block(f"Subagent task_name must be {expected_task}; do not substitute another lane.")
            return 0
        if requested_fork not in NO_HISTORY_VALUES:
            _block("Subagent spawn must use fork_turns=none so the full conversation history is not inherited.")
            return 0
        # This is deliberately the last mutation in the contract validator.
        # PreToolUse hooks continue after a block, so reserving in a later Sol
        # hook could poison a phase after this validator rejected the payload.
        if expected_route in {"sol-advisor", "sol-active-analysis"} and state.get("final_review_eligible"):
            phase = normalize_phase(state.get("phase")) or "plan"
            reserved, reason = reserve_sol_consultation(
                payload,
                phase,
                str(routing.get("decision_fingerprint") or ""),
            )
            if not reserved:
                _block(reason)
                return 0
    except Exception:
        # Ordinary tools remain fail-open, but once a native spawn has been
        # identified, a validation failure must fail closed at this trust
        # boundary instead of silently bypassing routing and RED controls.
        if native_tool in {"spawn_agent", "spawnagent"}:
            try:
                _block("Subagent routing validation failed; the spawn was blocked for safety.")
            except Exception:
                pass
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
