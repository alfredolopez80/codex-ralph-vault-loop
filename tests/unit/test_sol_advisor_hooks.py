from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.sol_advisor import (
    initialize,
    is_sol_advisor,
    mark_advisor,
    mark_stop_guard,
    needs_stop_review,
    observe_failure,
    read_state,
    state_path,
    executor_context,
    has_completion_evidence,
    has_fork_metadata,
    has_no_history_fork,
)
from shared.tool_result import success_from_payload


def payload(tmp_path: Path, **extra: object) -> dict[str, object]:
    return {
        "cwd": str(ROOT),
        "session_id": "sol-advisor-test",
        "complexity": 1,
        **extra,
    }


def test_material_decision_is_eligible_without_a_complexity_threshold(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, prompt="Review an authorization migration decision.")

    state = initialize(event)

    assert state is not None
    assert state["complexity"] == 1
    assert state["final_review_eligible"] is True
    persisted = state_path(event).read_text(encoding="utf-8")
    assert "authorization" in persisted
    assert "Review an authorization migration decision." not in persisted


def test_two_distinct_failures_make_an_existing_material_task_stuck_eligible(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, prompt="Decide the rollout architecture.")
    initialize(event)

    observe_failure({**event, "success": False, "command": "test first hypothesis"})
    result = observe_failure({**event, "success": False, "command": "test second hypothesis"})

    assert result["failure_count"] == 2
    assert result["stuck_eligible"] is True
    assert len(result["failure_fingerprints"]) == 2


def test_stop_guard_is_one_time_and_skips_completed_advice(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, prompt="Choose a database schema migration path.")
    initialize(event)
    state = read_state(event)
    assert needs_stop_review(state) is True

    mark_stop_guard(event)
    assert needs_stop_review(read_state(event)) is True

    event2 = {**event, "session_id": "sol-advisor-complete"}
    initialize(event2)
    mark_advisor(event2, completed=False)
    mark_advisor(event2, completed=True)
    assert needs_stop_review(read_state(event2)) is False


def test_continuation_keeps_existing_consultation_budget(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, prompt="Choose an external interface architecture.")
    initialize(event)
    mark_advisor(event, completed=False)

    continued = initialize({**event, "prompt": "continua con la validación"})

    assert continued is not None
    assert continued["consultation_count"] == 1
    assert continued["advisor_started"] is True


def test_low_impact_followup_preserves_pending_review(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, prompt="Choose an authorization architecture for rollout.")
    initialize(event)

    continued = initialize({**event, "prompt": "status update"})

    assert continued is not None
    assert continued["final_review_eligible"] is True
    assert continued["advisor_completed"] is False
    assert needs_stop_review(read_state(event)) is True


def test_low_impact_followup_preserves_completed_review(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, prompt="Choose an authorization architecture for rollout.")
    initialize(event)
    mark_advisor(event, completed=True)

    continued = initialize({**event, "prompt": "status update"})

    assert continued is not None
    assert continued["final_review_eligible"] is True
    assert continued["advisor_completed"] is True
    assert needs_stop_review(continued) is False


def test_explicit_new_task_starts_fresh_advisor_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, prompt="Choose an authorization architecture for rollout.")
    initialize(event)
    mark_advisor(event, completed=True)

    fresh = initialize({**event, "new_task": True, "prompt": "Explain the repository status."})

    assert fresh is not None
    assert fresh["final_review_eligible"] is False
    assert fresh["advisor_completed"] is False
    assert needs_stop_review(fresh) is False


def test_failure_observer_uses_exit_code_result_contract(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, prompt="Decide the rollout architecture.")
    initialize(event)

    observe_failure({**event, "exit_code": 1, "command": "first failing hypothesis"})
    result = observe_failure({**event, "returncode": 2, "command": "second failing hypothesis"})

    assert result["failure_count"] == 2
    assert result["stuck_eligible"] is True


def test_tool_result_normalization_preserves_unknown_and_success_states() -> None:
    assert success_from_payload({"exit_code": 1}) is False
    assert success_from_payload({"returncode": 0}) is True
    assert success_from_payload({"tool_response": {"return_code": 1}}) is False
    assert success_from_payload({"success": True, "exit_code": 1}) is True
    assert success_from_payload({"exit_code": "1"}) is None
    assert success_from_payload({}) is None


def test_name_or_model_identifies_the_native_sol_advisor() -> None:
    assert is_sol_advisor({"agent_type": "sol-advisor"}) is True
    assert is_sol_advisor({"agentType": "sol_advisor"}) is True
    assert is_sol_advisor({"tool_input": {"task_name": "sol_advisor", "model": "gpt-5.6-sol"}}) is True
    assert is_sol_advisor({"subagent": {"modelName": "gpt-5.6-sol"}}) is True
    assert is_sol_advisor({"agent_name": "ralph-reviewer"}) is False


def test_typed_advisor_requires_an_explicit_no_history_fork() -> None:
    assert has_no_history_fork({"tool_input": {"agent_type": "sol-advisor", "fork_turns": "none"}}) is True
    assert has_no_history_fork({"tool_input": {"agent_type": "sol-advisor", "fork_turns": "all"}}) is False
    assert has_fork_metadata({"tool_input": {"agent_type": "sol-advisor", "fork_turns": "all"}}) is True
    assert has_fork_metadata({"tool_input": {"agent_type": "sol-advisor"}}) is False


def test_advisor_completion_requires_success_and_an_execution_identity() -> None:
    assert has_completion_evidence({"success": True, "agent_id": "agent-1"}) is True
    assert has_completion_evidence({"success": True, "agent_type": "sol-advisor"}) is False
    assert has_completion_evidence({"success": False, "agent_id": "agent-1"}) is False


def test_executor_context_requires_a_minimized_no_history_advisor_fork() -> None:
    context = executor_context({"consultation_eligible": True, "complexity": 4, "impact_reasons": ["migration"]})

    assert "spawn_agent" in context
    assert "fork_turns=`none`" in context
    assert "model=`gpt-5.6-sol`" in context
    assert "compact decision brief" in context


def test_high_impact_lifecycle_requires_completed_advice(tmp_path: Path, monkeypatch) -> None:
    state_root = tmp_path / "state"
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(state_root))
    event = payload(tmp_path, prompt="Choose an authorization architecture for a public rollout.")
    initialize(event)

    def run_hook(name: str, hook_payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(HOOKS / name)],
            cwd=ROOT,
            input=json.dumps(hook_payload),
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "CODEX_HOOK_STATE_ROOT": str(state_root)},
        )

    wrong_fork = run_hook(
        "sol_advisor_pretool_guard.py",
        {**event, "tool_input": {"task_name": "sol_advisor", "model": "gpt-5.6-sol", "fork_turns": "all"}},
    )
    assert wrong_fork.returncode == 0
    assert json.loads(wrong_fork.stdout)["decision"] == "block"

    omitted_fork = run_hook(
        "sol_advisor_pretool_guard.py",
        {**event, "tool_input": {"task_name": "sol_advisor", "model": "gpt-5.6-sol"}},
    )
    assert omitted_fork.returncode == 0
    assert omitted_fork.stdout == ""

    waiting = run_hook("sol_advisor_stop_guard.py", event)
    assert waiting.returncode == 0
    assert json.loads(waiting.stdout)["decision"] == "block"

    completed = run_hook(
        "sol_advisor_subagent_stop.py",
        {**event, "task_name": "sol_advisor", "model": "gpt-5.6-sol", "agent_id": "advisor-run-1", "success": True},
    )
    assert completed.returncode == 0
    released = run_hook("sol_advisor_stop_guard.py", event)
    assert released.returncode == 0
    assert released.stdout == ""
