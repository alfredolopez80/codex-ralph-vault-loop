from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.runtime_budget import (
    MIN_CLEANUP_MARGIN_SECONDS,
    child_timeout_for,
    context_capable_events,
    context_limit_for,
    external_timeout_for,
)


@pytest.mark.parametrize("role", ["user_prompt_capture", "user_prompt_dispatch"])
def test_intake_child_timeout_leaves_cleanup_margin(role: str) -> None:
    child = child_timeout_for("UserPromptSubmit", role)
    external = external_timeout_for("UserPromptSubmit", role)
    assert child + MIN_CLEANUP_MARGIN_SECONDS < external


def test_context_limits_are_positive_and_bounded() -> None:
    assert context_limit_for("SessionStart") == 800
    assert context_limit_for("UserPromptSubmit") == 500
    assert context_limit_for("SubagentStart") == 16_384
    assert all(0 < context_limit_for(event) <= 16_384 for event in context_capable_events())


def test_runtime_budgets_are_codex_integer_values() -> None:
    pairs = [
        ("SessionStart", "session_start_dispatch"),
        ("UserPromptSubmit", "user_prompt_dispatch"),
        ("UserPromptSubmit", "user_prompt_capture"),
        ("PreToolUse", "pre_tool_dispatch"),
        ("PostToolUse", "post_tool_dispatch"),
        ("SubagentStart", "sol_advisor_subagent_context"),
        ("SubagentStop", "sol_advisor_subagent_stop"),
        ("Stop", "stop_dispatch"),
    ]
    for event, role in pairs:
        timeout = external_timeout_for(event, role)
        assert type(timeout) is int
        assert timeout > 0

    for role in ("user_prompt_capture", "user_prompt_dispatch"):
        child = child_timeout_for("UserPromptSubmit", role)
        assert type(child) is int
        assert child > 0


@pytest.mark.parametrize("event", ["PreToolUse", "PostToolUse", "SubagentStop", "Stop"])
def test_context_limits_reject_unsupported_events(event: str) -> None:
    with pytest.raises(ValueError):
        context_limit_for(event)


def test_unknown_runtime_pairs_fail_loud() -> None:
    with pytest.raises(ValueError):
        external_timeout_for("Unknown", "missing")
    with pytest.raises(ValueError):
        child_timeout_for("Stop", "stop_dispatch")
