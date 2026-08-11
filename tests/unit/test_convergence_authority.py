from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.convergence_authority import AuthorityError, ensure_prompt_boundary, load_authoritative_state  # noqa: E402


def test_shadow_without_an_active_plan_is_bounded_and_nonblocking(tmp_path: Path) -> None:
    result = ensure_prompt_boundary(
        {"cwd": str(tmp_path), "session_id": "session-a", "prompt": "implement the change"},
        prompt="implement the change",
        boundary={"boundary_kind": "new_task", "risk": "low", "complexity": 1},
        mode="shadow",
    )
    assert result is not None
    assert result["state_available"] is False
    assert result["plan_id"] == ""


def test_shadow_normalizes_policy_boundary_aliases(tmp_path: Path) -> None:
    result = ensure_prompt_boundary(
        {"cwd": str(tmp_path), "session_id": "session-a", "prompt": "implement the change"},
        prompt="implement the change",
        boundary={"boundary_kind": "new-task", "risk": "low", "complexity": 1},
        mode="shadow",
    )
    assert result is not None
    assert result["boundary_kind"] == "new_task"


def test_enforce_never_uses_a_caller_snapshot_without_canonical_state(tmp_path: Path) -> None:
    payload = {
        "cwd": str(tmp_path),
        "session_id": "session-a",
        "task_signature": "task-a",
        "convergence_state": {"schema_version": 3, "status": "closed"},
    }
    with pytest.raises(AuthorityError, match="convergent-(authority|state)-"):
        load_authoritative_state(payload)
