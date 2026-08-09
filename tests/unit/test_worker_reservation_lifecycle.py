from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.sol_advisor import initialize, observe_failure, read_state, reserve_worker_spawn


def _task(tmp_path: Path) -> dict[str, object]:
    return {
        "cwd": str(tmp_path),
        "session_id": "terra-reservation",
        "prompt": "Implement one independent bounded migration component.",
        "complexity": 4,
        "intent": "implementation",
        "independent_block": True,
    }


def _spawn(task: dict[str, object], state: dict[str, object], invocation: str) -> dict[str, object]:
    routing = state["routing"]
    assert isinstance(routing, dict)
    arguments = routing["spawn_arguments"]
    assert isinstance(arguments, dict)
    return {
        **task,
        "hook_event_name": "PreToolUse",
        "tool_name": "spawn_agent",
        "tool_input": {
            **arguments,
            "invocation_id": invocation,
            "message": "Implement only the bounded independent component.",
        },
    }


def test_failed_terra_spawn_releases_only_its_reservation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    task = _task(tmp_path)
    state = initialize(task)
    assert state and state["routing"]["subagent_route"] == "terra-implementation"
    spawn = _spawn(task, state, "terra-1")
    assert reserve_worker_spawn(spawn)[0] is True
    assert read_state(task)["agent_budget"]["worker_reserved_jobs"] == 1

    unrelated = _spawn(task, state, "terra-other")
    observe_failure({**unrelated, "hook_event_name": "PostToolUse", "success": False})
    assert read_state(task)["agent_budget"]["worker_reserved_jobs"] == 1

    observe_failure({**spawn, "hook_event_name": "PostToolUse", "success": False})
    released = read_state(task)["agent_budget"]
    assert released["worker_reserved_jobs"] == 0
    assert released["reserved_jobs"] == 0
    assert reserve_worker_spawn(spawn)[0] is True


def test_successful_terra_spawn_converts_reservation_to_started_worker(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    task = _task(tmp_path)
    state = initialize(task)
    assert state
    spawn = _spawn(task, state, "terra-success")
    assert reserve_worker_spawn(spawn)[0] is True
    observe_failure({**spawn, "hook_event_name": "PostToolUse", "success": True})
    ledger = read_state(task)["agent_budget"]
    assert ledger["worker_reserved_jobs"] == 0
    assert ledger["reserved_jobs"] == 0
    assert ledger["workers_started"] == 1
    assert ledger["agents_started"] == 1
