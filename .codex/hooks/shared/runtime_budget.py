"""Single source of truth for interactive hook runtime/context budgets."""
from __future__ import annotations

from typing import Final


MIN_CLEANUP_MARGIN_SECONDS: Final[float] = 1.0

_EXTERNAL_TIMEOUTS: Final[dict[tuple[str, str], float]] = {
    ("SessionStart", "session_start_dispatch"): 45.0,
    ("UserPromptSubmit", "user_prompt_dispatch"): 10.0,
    ("UserPromptSubmit", "user_prompt_capture"): 10.0,
    ("PreToolUse", "pre_tool_dispatch"): 10.0,
    ("PostToolUse", "post_tool_dispatch"): 10.0,
    ("SubagentStart", "sol_advisor_subagent_context"): 10.0,
    ("SubagentStop", "sol_advisor_subagent_stop"): 10.0,
    ("Stop", "stop_dispatch"): 10.0,
}

_CHILD_TIMEOUTS: Final[dict[tuple[str, str], float]] = {
    # Leaves two seconds for explicit fallback, telemetry and interpreter exit.
    ("UserPromptSubmit", "user_prompt_capture"): 8.0,
    ("UserPromptSubmit", "user_prompt_dispatch"): 8.0,
}

_CONTEXT_LIMITS: Final[dict[tuple[str, str], int]] = {
    ("SessionStart", "default"): 800,
    ("UserPromptSubmit", "default"): 500,
    ("SubagentStart", "default"): 400,
}


def external_timeout_for(event: str, role: str) -> float:
    """Return the configured outer timeout, failing loud for unknown pairs."""
    try:
        return _EXTERNAL_TIMEOUTS[(event, role)]
    except KeyError as exc:
        raise ValueError(f"unknown hook runtime budget: {event}/{role}") from exc


def child_timeout_for(event: str, role: str) -> float:
    """Return a child timeout proven to leave at least the cleanup margin."""
    try:
        child = _CHILD_TIMEOUTS[(event, role)]
    except KeyError as exc:
        raise ValueError(f"hook role has no child-process budget: {event}/{role}") from exc
    external = external_timeout_for(event, role)
    if child + MIN_CLEANUP_MARGIN_SECONDS >= external:
        raise RuntimeError(f"invalid hook timeout budget: {event}/{role}")
    return child


def context_limit_for(event: str, profile: str = "default") -> int:
    """Return a positive approximate-token cap for context-capable events."""
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
