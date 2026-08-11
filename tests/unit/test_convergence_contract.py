from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.convergent_contracts import ContractError, TaskIdentity, new_state, state_hash, validate_state  # noqa: E402
from shared.execution_policy import load_execution_policy  # noqa: E402
from shared.goal_compiler import PLAN_ID  # noqa: E402


PLAN_DIGEST = "sha256:fead6e85227c68c863fa23ccccc30f559c3893ced514704f5643c61d1c41b5e1"


def _identity() -> TaskIdentity:
    return TaskIdentity.from_values(
        session="contract-session",
        project="contract-project",
        worktree="contract-worktree",
        branch="codex/ralph-convergent-execution-v4",
        objective="Validate the convergent identity contract",
        boundary_epoch=1,
        sensitivity="GREEN",
        plan=PLAN_ID,
        plan_version=1,
        plan_digest=PLAN_DIGEST,
    )


def _state() -> dict[str, object]:
    return new_state(
        policy=load_execution_policy(),
        plan_id=PLAN_ID,
        plan_version=1,
        plan_digest=PLAN_DIGEST,
        task_identity=_identity(),
        goal_id="G-BASELINE",
        task_epoch="epoch-contract",
        boundary_epoch=1,
        boundary_kind="new_task",
        activation_mode="shadow",
    )


@pytest.mark.parametrize(
    ("public_field", "legacy_field", "replacement"),
    (
        ("branch", "branch_hash", "codex/other-branch"),
        ("sensitivity", "sensitivity_hash", "YELLOW"),
        ("plan_id", "plan_hash", "another-plan"),
        ("plan_version", "plan_version_hash", 2),
    ),
)
def test_identity_rejects_public_legacy_alias_drift(public_field: str, legacy_field: str, replacement: object) -> None:
    identity = _identity().as_dict()
    identity[public_field] = replacement
    with pytest.raises(ContractError, match="alias drift"):
        validate_state({**_state(), "task_identity": identity})


@pytest.mark.parametrize(
    ("state_field", "replacement"),
    (("plan_id", "another-plan"), ("plan_version", 2), ("plan_digest", "sha256:" + "0" * 64), ("boundary_epoch", 2)),
)
def test_state_rejects_top_level_identity_drift(state_field: str, replacement: object) -> None:
    state = _state()
    state[state_field] = replacement
    state["state_hash"] = ""
    state["state_hash"] = state_hash(state)
    with pytest.raises(ContractError, match="state/task identity drift"):
        validate_state(state)


def test_identity_as_dict_preserves_typed_public_fields() -> None:
    values = _identity().as_dict()
    assert isinstance(values["boundary_epoch"], int)
    assert isinstance(values["plan_version"], int)
    assert values["branch"] == "codex/ralph-convergent-execution-v4"
