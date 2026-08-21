"""Single source of truth for interactive hook runtime/context budgets."""
from __future__ import annotations

from typing import Final


MIN_CLEANUP_MARGIN_SECONDS: Final[float] = 1.0

_EXTERNAL_TIMEOUTS: Final[dict[tuple[str, str], int]] = {
    ("SessionStart", "session_start_dispatch"): 45,
    ("UserPromptSubmit", "user_prompt_dispatch"): 10,
    ("UserPromptSubmit", "user_prompt_capture"): 10,
    ("PreToolUse", "pre_tool_dispatch"): 10,
    ("PostToolUse", "post_tool_dispatch"): 10,
    ("SubagentStart", "sol_advisor_subagent_context"): 10,
    ("SubagentStop", "sol_advisor_subagent_stop"): 10,
    ("Stop", "stop_dispatch"): 10,
}

_CHILD_TIMEOUTS: Final[dict[tuple[str, str], int]] = {
    # Leaves two seconds for explicit fallback, telemetry and interpreter exit.
    ("UserPromptSubmit", "user_prompt_capture"): 8,
    ("UserPromptSubmit", "user_prompt_dispatch"): 8,
}

_CONTEXT_LIMITS: Final[dict[tuple[str, str], int]] = {
    ("SessionStart", "default"): 800,
    ("UserPromptSubmit", "default"): 500,
    # Capacity ceiling, not an eager allocation. The ordinary advisor packet
    # remains compact, while complex subagents can receive an explicit brief
    # without Codex collapsing it to a short preview.
    ("SubagentStart", "default"): 16_384,
}


def external_timeout_for(event: str, role: str) -> int:
    """Return the Codex-compatible integer outer timeout."""
    try:
        return _EXTERNAL_TIMEOUTS[(event, role)]
    except KeyError as exc:
        raise ValueError(f"unknown hook runtime budget: {event}/{role}") from exc


def child_timeout_for(event: str, role: str) -> int:
    """Return an integer child timeout with the cleanup margin preserved."""
    try:
        child = _CHILD_TIMEOUTS[(event, role)]
    except KeyError as exc:
        raise ValueError(f"hook role has no child-process budget: {event}/{role}") from exc
    external = external_timeout_for(event, role)
    if child + MIN_CLEANUP_MARGIN_SECONDS >= external:
        raise RuntimeError(f"invalid hook timeout budget: {event}/{role}")
    return child


def context_limit_for(event: str, profile: str = "default") -> int:
    """Return a positive Codex additional-context preview cap."""
    try:
        limit = _CONTEXT_LIMITS[(event, profile)]
    except KeyError as exc:
        raise ValueError(f"event/profile has no additional-context budget: {event}/{profile}") from exc
    if limit <= 0:
        raise RuntimeError(f"invalid additional-context budget: {event}/{profile}")
    return limit


def context_capable_events() -> frozenset[str]:
    return frozenset(event for event, _profile in _CONTEXT_LIMITS)


__all__ = [
    "MIN_CLEANUP_MARGIN_SECONDS",
    "child_timeout_for",
    "context_capable_events",
    "context_limit_for",
    "external_timeout_for",
]
