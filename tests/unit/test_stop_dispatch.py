from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".codex" / "hooks" / "stop_dispatch.py"


def run_dispatch(tmp_path: Path, payload: dict, *, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "RALPH_HOME": str(tmp_path / "ralph"),
            "CODEX_MEMORY_HOME": str(tmp_path / "empty-codex-memory"),
            "VAULT_DIR": str(tmp_path / "empty-vault"),
            "RALPH_LOCAL_NOTES_ROOTS": "",
            "CODEX_HOOK_STATE_ROOT": str(tmp_path / "hook-state"),
            "CODEX_SLOP_GUARD_ENABLED": "0",
        }
    )
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=10,
    )


def payload(tmp_path: Path, session: str = "session-a", task: str = "task-a") -> dict:
    return {
        "hook_event_name": "Stop",
        "cwd": str(tmp_path),
        "session_id": session,
        "turn_id": "turn-1",
        "task_signature": task,
        "last_assistant_message": "The implementation is probably complete.",
    }


def state_for(tmp_path: Path, *, session: str = "session-a", task: str = "task-a", **extra: object) -> dict[str, object]:
    state: dict[str, object] = {
        "schema_version": 1,
        "session_id": session,
        "task_signature": "task-" + hashlib.sha256(task.encode()).hexdigest()[:32],
        "workspace_root": str(tmp_path),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    state.update(extra)
    return state


def parse_output(result: subprocess.CompletedProcess[str]) -> dict[str, object] | None:
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("\n") <= 1
    if not result.stdout.strip():
        return None
    decoded = json.loads(result.stdout)
    assert set(decoded) == {"decision", "reason"}
    assert decoded["decision"] == "block"
    assert isinstance(decoded["reason"], str) and decoded["reason"]
    return decoded


def test_no_active_state_allows_with_empty_stdout(tmp_path: Path) -> None:
    result = run_dispatch(tmp_path, payload(tmp_path))
    assert parse_output(result) is None


def test_invalid_payload_fails_open_with_sanitized_stderr(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.update({"RALPH_HOME": str(tmp_path / "ralph")})
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        cwd=ROOT,
        input="[invalid",
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert "invalid JSON payload" in result.stderr


def test_verified_done_true_allows(tmp_path: Path) -> None:
    event = payload(tmp_path)
    event["objective_state"] = state_for(tmp_path, verified_done=True)
    assert parse_output(run_dispatch(tmp_path, event)) is None


def test_scoped_verified_done_false_blocks(tmp_path: Path) -> None:
    event = payload(tmp_path, task="verified-false")
    event["objective_state"] = state_for(tmp_path, task="verified-false", verified_done=False)
    result = parse_output(run_dispatch(tmp_path, event))
    assert result is not None
    assert "verified" in str(result["reason"]).lower()


def test_pending_current_state_gets_one_continuation_then_allows(tmp_path: Path) -> None:
    event = payload(tmp_path)
    event["objective_state"] = state_for(tmp_path, status="pending", pending_tasks=1)
    first_result = run_dispatch(tmp_path, event)
    first = parse_output(first_result)
    second = parse_output(run_dispatch(tmp_path, event))
    assert first is not None, (first_result.stdout, first_result.stderr)
    assert "pending" in str(first["reason"]).lower()
    assert second is None


def test_new_turn_for_same_task_does_not_reset_continuation_budget(tmp_path: Path) -> None:
    event = payload(tmp_path, task="same-task-across-turns")
    event["tests_failed"] = True
    event["critical"] = False
    first = parse_output(run_dispatch(tmp_path, event))
    assert first is not None

    next_turn = dict(event)
    next_turn["turn_id"] = "turn-2"
    assert parse_output(run_dispatch(tmp_path, next_turn)) is None


def test_stop_hook_active_allows_immediately_without_persistence(tmp_path: Path) -> None:
    event = payload(tmp_path)
    event["stop_hook_active"] = True
    result = run_dispatch(tmp_path, event)
    assert parse_output(result) is None
    assert not (tmp_path / "ralph").exists()


def test_foreign_session_state_is_ignored(tmp_path: Path) -> None:
    event = payload(tmp_path, session="session-a")
    event["objective_state"] = state_for(tmp_path, session="session-b", status="pending", pending_tasks=1)
    assert parse_output(run_dispatch(tmp_path, event)) is None


def test_unscoped_state_is_report_only(tmp_path: Path) -> None:
    event = payload(tmp_path)
    event["objective_state"] = {"status": "pending", "pending_tasks": 1}
    assert parse_output(run_dispatch(tmp_path, event)) is None
    reports = list((tmp_path / "ralph").rglob("stop-events.jsonl"))
    assert reports
    assert "unscoped" in reports[0].read_text(encoding="utf-8")


def test_state_without_task_identity_is_report_only(tmp_path: Path) -> None:
    event = payload(tmp_path)
    event["objective_state"] = {"session_id": "session-a", "status": "pending", "pending_tasks": 1}
    assert parse_output(run_dispatch(tmp_path, event)) is None


def test_expired_state_is_ignored(tmp_path: Path) -> None:
    event = payload(tmp_path)
    event["objective_state"] = state_for(
        tmp_path,
        status="pending",
        pending_tasks=1,
        updated_at=(datetime.now(UTC) - timedelta(days=3)).isoformat(),
    )
    assert parse_output(run_dispatch(tmp_path, event, extra_env={"RALPH_STOP_STATE_TTL_SECONDS": "60"})) is None


def test_probably_without_objective_failure_does_not_block(tmp_path: Path) -> None:
    assert parse_output(run_dispatch(tmp_path, payload(tmp_path))) is None


def test_failed_tests_block_but_passed_tests_allow(tmp_path: Path) -> None:
    failed = payload(tmp_path, task="test-task")
    failed.update({"tests_failed": True, "test_command": "pytest", "critical": False})
    assert parse_output(run_dispatch(tmp_path, failed)) is not None

    passed = payload(tmp_path, task="passing-task")
    passed.update({"tests_failed": False, "tests_passed": True})
    assert parse_output(run_dispatch(tmp_path, passed)) is None


def test_quality_state_preserves_unexecuted_and_incomplete_objective_gates(tmp_path: Path) -> None:
    unexecuted = payload(tmp_path, task="unexecuted")
    unexecuted["objective_state"] = state_for(tmp_path, task="unexecuted", conditions={"tests_executed": False})
    assert "tests" in str(parse_output(run_dispatch(tmp_path, unexecuted))["reason"]).lower()

    incomplete = payload(tmp_path, task="incomplete")
    incomplete["objective_state"] = state_for(tmp_path, task="incomplete", implementation_complete=False)
    assert "incomplete" in str(parse_output(run_dispatch(tmp_path, incomplete))["reason"]).lower()


def test_scoped_active_loop_is_objective_evidence(tmp_path: Path) -> None:
    event = payload(tmp_path, task="loop-task")
    event["objective_state"] = state_for(tmp_path, task="loop-task", kind="loop", iteration=2, max_iterations=5)
    result = parse_output(run_dispatch(tmp_path, event))
    assert result is not None
    assert "loop" in str(result["reason"]).lower()


def test_file_line_violation_is_a_hard_gate(tmp_path: Path) -> None:
    oversized = tmp_path / "new_module.py"
    oversized.write_text("x\n" * 351, encoding="utf-8")
    event = payload(tmp_path, task="file-line")
    event["tool_input"] = {"file_path": str(oversized)}
    result = parse_output(run_dispatch(tmp_path, event))
    assert result is not None
    assert "file-line" in str(result["reason"]).lower()


def test_required_implementation_notes_are_a_hard_gate(tmp_path: Path) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True, text=True)
    plan = tmp_path / ".ralph" / "plans" / "phase-plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "# Phase plan\n\nImplementation notes required: yes\nPlan approval status: approved\n",
        encoding="utf-8",
    )
    event = payload(tmp_path, task="notes-gate")
    event["implementation_plan_path"] = str(plan)
    result = parse_output(run_dispatch(tmp_path, event))
    assert result is not None
    assert "implementation notes" in str(result["reason"]).lower()


def test_two_reasons_are_one_compact_block(tmp_path: Path) -> None:
    event = payload(tmp_path, task="two-reasons")
    event.update({"tests_failed": True, "integrity_failure": True, "critical": True})
    result = parse_output(run_dispatch(tmp_path, event))
    assert result is not None
    reason = str(result["reason"])
    assert reason.count(";") <= 2
    assert "integrity" in reason.lower()


def test_same_reason_does_not_loop_and_new_critical_fingerprint_gets_one_last_retry(tmp_path: Path) -> None:
    first = payload(tmp_path, session="critical-session", task="critical-task")
    first.update({"tests_failed": True, "critical": True, "evidence_fingerprint": "failure-a"})
    assert parse_output(run_dispatch(tmp_path, first)) is not None
    assert parse_output(run_dispatch(tmp_path, first)) is None

    second = dict(first)
    second["evidence_fingerprint"] = "failure-b"
    assert parse_output(run_dispatch(tmp_path, second)) is not None
    assert parse_output(run_dispatch(tmp_path, second)) is None


def test_corrupt_budget_recovers_and_still_requires_independent_evidence(tmp_path: Path) -> None:
    event = payload(tmp_path, task="corrupt-budget")
    seed = dict(event)
    seed.update({"tests_failed": True, "evidence_fingerprint": "seed"})
    assert parse_output(run_dispatch(tmp_path, seed)) is not None
    budget_files = list((tmp_path / "ralph").rglob("continuation.json"))
    assert budget_files
    budget_files[0].write_text('{"broken":', encoding="utf-8")

    no_evidence = parse_output(run_dispatch(tmp_path, event))
    assert no_evidence is None
    failing = dict(event)
    failing.update({"tests_failed": True, "evidence_fingerprint": "independent"})
    assert parse_output(run_dispatch(tmp_path, failing)) is not None
    assert list(budget_files[0].parent.glob("continuation.invalid.*.json"))


def test_route_marker_absence_is_report_only(tmp_path: Path) -> None:
    event = payload(tmp_path)
    event.update({"tool_call_count": 5, "turn_count": 8})
    assert parse_output(run_dispatch(tmp_path, event)) is None
    reports = list((tmp_path / "ralph").rglob("stop-events.jsonl"))
    assert reports
    text = "\n".join(path.read_text(encoding="utf-8") for path in reports)
    assert "route_marker_missing" in text


def test_handoff_marker_is_bounded_and_does_not_store_message_body(tmp_path: Path) -> None:
    marker = "SENTINEL_STOP_MESSAGE_92817"
    event = payload(tmp_path)
    event["last_assistant_message"] = marker
    event["learning_candidate"] = {"id": "candidate-1"}
    result = run_dispatch(tmp_path, event)
    assert parse_output(result) is None
    before = sorted((tmp_path / "ralph").rglob("handoffs/*.md"))
    assert len(before) == 2
    assert parse_output(run_dispatch(tmp_path, event)) is None
    assert sorted((tmp_path / "ralph").rglob("handoffs/*.md")) == before
    marker_files = list((tmp_path / "ralph").rglob("promotion-pending.jsonl"))
    assert marker_files
    assert marker not in marker_files[0].read_text(encoding="utf-8")
    assert list((tmp_path / "ralph").rglob("handoffs/latest.md"))


def test_dispatcher_is_the_only_configured_stop_command() -> None:
    config = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    stop_hooks = config["hooks"]["Stop"][0]["hooks"]
    commands = [str(item["command"]) for item in stop_hooks]
    assert len(commands) == 1
    assert commands[0].endswith(".codex/hooks/stop_dispatch.py")
