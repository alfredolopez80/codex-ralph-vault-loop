from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.convergent_contracts import TaskIdentity, new_state, state_hash  # noqa: E402
from shared.convergent_stop import terminal_attempt_fingerprint  # noqa: E402
from shared.convergent_stop_adapter import evaluate_convergent_stop  # noqa: E402
from shared.execution_lease import LeaseEvidence, acquire_execution_lease  # noqa: E402
from shared.execution_policy import load_execution_policy  # noqa: E402
from shared.goal_compiler import PLAN_ID  # noqa: E402

PLAN_DIGEST = "sha256:fead6e85227c68c863fa23ccccc30f559c3893ced514704f5643c61d1c41b5e1"


def _state() -> dict[str, object]:
    identity = TaskIdentity.from_values(
        session="adapter-session",
        project="adapter-project",
        worktree="adapter-worktree",
        branch="codex/ralph-convergent-execution-v4",
        objective="Validate the Stop adapter",
        boundary_epoch=1,
        sensitivity="GREEN",
        plan=PLAN_ID,
        plan_version=1,
        plan_digest=PLAN_DIGEST,
    )
    state = new_state(
        policy=load_execution_policy(),
        plan_id=PLAN_ID,
        plan_version=1,
        plan_digest=PLAN_DIGEST,
        task_identity=identity,
        goal_id="G-EVIDENCE-CLOSE",
        task_epoch="epoch-adapter",
        boundary_epoch=1,
        boundary_kind="new_task",
        activation_mode="shadow",
    )
    state["phase"] = "stop"
    state["execution_lease"] = acquire_execution_lease(
        LeaseEvidence(
            model="gpt-5.6-sol",
            reasoning_effort="max",
            tools=("apply_patch", "exec_command"),
            cwd=str(ROOT),
            branch="codex/ralph-convergent-execution-v4",
            task_epoch="epoch-adapter",
            owner_role="sol-worker",
            authority_role="codex-main",
            source="verified-runtime",
        ),
        policy=load_execution_policy(),
        issued_generation=state["generation"],
    ).as_dict()
    state["state_hash"] = state_hash(state)
    return state


def test_missing_snapshot_is_legacy_path() -> None:
    assert evaluate_convergent_stop({}) is None


def test_invalid_explicit_snapshot_is_blocking() -> None:
    result = evaluate_convergent_stop({"convergence_state": {"raw_prompt": "must not persist"}})
    assert result is not None
    assert result.action == "block"
    assert result.reason == "convergent-state-invalid"


def test_incomplete_snapshot_is_authoritatively_blocked() -> None:
    result = evaluate_convergent_stop({"convergence_state": _state()})
    assert result is not None
    assert result.action == "block"
    assert result.reason == "objective-evidence-incomplete"


def test_duplicate_terminal_attempt_is_a_physical_noop() -> None:
    state = _state()
    fingerprint = terminal_attempt_fingerprint(state)
    result = evaluate_convergent_stop(
        {
            "convergence_state": state,
            "terminal_attempt_fingerprint": fingerprint,
            "previous_terminal_fingerprint": fingerprint,
        }
    )
    assert result is not None
    assert result.action == "physical-no-op"
    assert result.physical_no_op is True
