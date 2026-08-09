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
    assert context_limit_for("SubagentStart") == 400
    assert all(0 < context_limit_for(event) <= 800 for event in context_capable_events())


@pytest.mark.parametrize("event", ["PreToolUse", "PostToolUse", "SubagentStop", "Stop"])
def test_context_limits_reject_unsupported_events(event: str) -> None:
    with pytest.raises(ValueError):
        context_limit_for(event)


def test_unknown_runtime_pairs_fail_loud() -> None:
    with pytest.raises(ValueError):
        external_timeout_for("Unknown", "missing")
    with pytest.raises(ValueError):
        child_timeout_for("Stop", "stop_dispatch")
