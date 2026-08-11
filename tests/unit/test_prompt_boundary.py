from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".codex" / "hooks"))

from shared.prompt_boundary import classify_boundary  # noqa: E402


def test_prompt_boundary_returns_exact_contract_shape() -> None:
    result = classify_boundary("status of the current phase?")
    assert result.as_dict() == {
        "boundary_kind": "status_only",
        "risk": "low",
        "complexity": 1,
        "scope_delta": False,
        "obligation_delta": False,
        "approval_delta": False,
    }


def test_long_mechanical_prompt_does_not_create_critical_task() -> None:
    prompt = "read the following files and summarize them: " + ("read-only context " * 400)
    result = classify_boundary(prompt)
    assert result.boundary_kind == "new_task"
    assert result.risk == "low"
    assert result.complexity == 1


def test_short_authorization_prompt_is_critical() -> None:
    result = classify_boundary("authorize production migration", {"active_task": True})
    assert result.boundary_kind == "new_task"
    assert result.risk == "critical"
    assert result.approval_delta is True


def test_continuation_and_material_change_are_distinct() -> None:
    assert classify_boundary("continue with the next step").boundary_kind == "continuation"
    material = classify_boundary("new evidence contradicts the architecture", {"active_task": True})
    assert material.boundary_kind == "material_change"
    assert material.scope_delta is False


def test_explicit_user_override_wins_over_other_signals() -> None:
    result = classify_boundary("override and run a second audit", {"user_override": True})
    assert result.boundary_kind == "user_override"
    assert result.risk == "critical"


def test_policy_class_aliases_map_to_the_wire_boundary_kinds() -> None:
    expected = {
        "status": "status_only",
        "continuation": "continuation",
        "clarification": "clarification",
        "new-task": "new_task",
        "scope-extension": "scope_extension",
        "material-change": "material_change",
        "user-override": "user_override",
    }
    for supplied, wire_kind in expected.items():
        result = classify_boundary("mechanical request", {"boundary_kind": supplied, "active_task": True})
        assert result.boundary_kind == wire_kind
        if supplied == "user-override":
            assert result.risk == "critical" and result.approval_delta is True


def test_read_only_architecture_is_low_but_material_actions_keep_declared_risk() -> None:
    assert classify_boundary("read README.md and summarize the architecture").risk == "low"
    for prompt in (
        "implement the bounded policy parser",
        "run focused verification for the candidate",
        "design a versioned decision packet",
        "mitigate accepted findings in one batch",
    ):
        assert classify_boundary(prompt).risk == "material"


def test_complete_concurrency_terms_are_critical() -> None:
    assert classify_boundary("change concurrent writers and CAS semantics").risk == "critical"
    assert classify_boundary("repair the concurrency contract").risk == "critical"
