from __future__ import annotations

import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"

if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.active_context import active_context_from_payload  # noqa: E402
from shared.checkpoint_io import update_checkpoint  # noqa: E402
from shared.implementation_store import ImplementationStore, resolve_store_paths  # noqa: E402
from shared.progress_runtime import (  # noqa: E402
    complete_progress,
    progress_checkpoint_reference,
    structured_validation,
    validation_transition,
)


def _git(root: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def _fixture(tmp_path: Path, *, plan_text: str = "# Plan\nPlan approval status: approved\n") -> tuple[Path, ImplementationStore]:
    root = tmp_path / "primary"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Progress Test")
    plan = root / ".ralph" / "plans" / "progress.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(plan_text, encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture")
    store = ImplementationStore(resolve_store_paths(primary_root=root))
    store.register_plan(
        "progress",
        plan_path=".ralph/plans/progress.md",
        status="active",
        operation_id="start-fixture",
        now="2026-08-10T00:00:00+00:00",
    )
    return root, store


def _payload(root: Path, *, success: bool = True, command: str = "pytest -q", **extra: object) -> dict[str, object]:
    value: dict[str, object] = {
        "hook_event_name": "PostToolUse",
        "cwd": str(root),
        "primary_repo_root": str(root),
        "session_id": "progress-session",
        "tool_use_id": "tool-use-1",
        "tool_name": "exec_command",
        "tool_input": {"cmd": command},
        "tool_response": {"exit_code": 0 if success else 1, "stdout": "structured result"},
        "success": success,
        "model": "gpt-5.6-luna",
    }
    value.update(extra)
    return value


def test_structured_validation_rejects_ordinary_writes_and_accepts_gates() -> None:
    assert structured_validation(_payload(Path("."), command="touch tests/test_file.py")) is None
    assert structured_validation(_payload(Path("."), command="pytest -q")) == ("tests", "pass")
    assert structured_validation(_payload(Path("."), command="npm run lint", success=False)) == ("lint", "fail")


def test_validation_transition_is_semantic_and_failing_to_passing_changes_once(tmp_path: Path) -> None:
    root, store = _fixture(tmp_path)
    context = active_context_from_payload({"cwd": str(root), "session_id": "progress-session", "branch": "main"}, resolve_git=False)
    passed = validation_transition(_payload(root), context)
    assert passed.changed is True
    before = store.plan_paths("progress").events.read_bytes()
    repeated = validation_transition(_payload(root, tool_use_id="tool-use-2"), context)
    assert repeated.changed is False
    assert repeated.result.bytes_written == 0
    assert store.plan_paths("progress").events.read_bytes() == before
    failed = validation_transition(_payload(root, success=False, tool_use_id="tool-use-3"), context)
    assert failed.changed is True
    passing_again = validation_transition(_payload(root, tool_use_id="tool-use-4"), context)
    assert passing_again.changed is True
    assert store.read_state("progress")["validation"] == {"tests": "pass"}


def test_planned_checkpoint_contains_only_progress_reference(tmp_path: Path, monkeypatch) -> None:
    root, _store = _fixture(tmp_path)
    context = active_context_from_payload({"cwd": str(root), "session_id": "progress-session"}, resolve_git=False)
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    ref = progress_checkpoint_reference({**_payload(root), "progress_plan_id": "progress"}, context)
    assert ref and set(ref) == {"plan_id", "generation", "semantic_hash"}
    result = update_checkpoint({"progress_ref": ref, "progress_ref_only": True}, context=context)
    checkpoint = result["checkpoint"]
    assert checkpoint["progress_ref"] == ref
    assert checkpoint["objective"] == checkpoint["current_phase"] == checkpoint["next_action"] == ""
    assert checkpoint["commands_run"] == []
    assert not list((tmp_path / "ralph").rglob("archive/*.json"))


def test_checkpoint_and_completion_require_plan_approval_when_document_exists(tmp_path: Path) -> None:
    root, store = _fixture(tmp_path, plan_text="# Plan\nPlan approval status: pending\n")
    context = active_context_from_payload({"cwd": str(root), "session_id": "progress-session"}, resolve_git=False)
    payload = {**_payload(root), "progress_plan_id": "progress", "progress_complete": True}
    assert progress_checkpoint_reference(payload, context) is None
    transition = complete_progress(payload, context)
    assert transition.changed is False
    assert transition.error_code == "progress_approval_invalid"
    assert [event["kind"] for event in store.read_events("progress")] == ["started"]


def test_payload_approval_boolean_cannot_complete_an_undocumented_plan(tmp_path: Path) -> None:
    root = tmp_path / "primary"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Progress Test")
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture")
    store = ImplementationStore(resolve_store_paths(primary_root=root))
    store.register_plan("undocumented", status="active", operation_id="start-undocumented")
    context = active_context_from_payload({"cwd": str(root), "session_id": "progress-session"}, resolve_git=False)
    payload = {
        **_payload(root),
        "progress_plan_id": "undocumented",
        "plan_approved": True,
        "progress_complete": True,
        "validation_status": "pass",
    }

    assert progress_checkpoint_reference(payload, context) is None
    transition = complete_progress(payload, context)
    assert transition.changed is False
    assert transition.error_code == "progress_approval_invalid"
    assert [event["kind"] for event in store.read_events("undocumented")] == ["started"]


def test_stop_completion_is_one_terminal_transition_and_retry_is_read_only(tmp_path: Path) -> None:
    root, store = _fixture(tmp_path)
    context = active_context_from_payload({"cwd": str(root), "session_id": "progress-session", "branch": "main"}, resolve_git=False)
    assert validation_transition(_payload(root), context).changed
    stop = {
        **_payload(root),
        "hook_event_name": "Stop",
        "progress_plan_id": "progress",
        "progress_complete": True,
        "validation_status": "pass",
    }
    first = complete_progress(stop, context)
    assert first.changed is True
    events_before = store.plan_paths("progress").events.read_bytes()
    second = complete_progress(stop, context)
    assert second.changed is False
    assert store.plan_paths("progress").events.read_bytes() == events_before
    assert [event["kind"] for event in store.read_events("progress")].count("completed") == 1


def test_stop_completion_rejects_corrupt_state_and_survives_deleted_worktree(tmp_path: Path) -> None:
    root, store = _fixture(tmp_path)
    state = store.plan_paths("progress").state
    payload = {
        "hook_event_name": "Stop",
        "cwd": str(tmp_path / "deleted-worktree"),
        "primary_repo_root": str(root),
        "session_id": "progress-session",
        "progress_plan_id": "progress",
        "progress_complete": True,
    }
    context = active_context_from_payload(payload, resolve_git=False)
    state.write_text('{"schema_version":99}', encoding="utf-8")
    result = complete_progress(payload, context)
    assert result.changed is False
    assert result.error_code == "progress_state_corrupt"
    assert state.exists()


def test_stop_completion_rejects_future_schema_without_downgrade(tmp_path: Path) -> None:
    root, store = _fixture(tmp_path)
    state = store.plan_paths("progress").state
    state.write_text('{"schema_version": 999}', encoding="utf-8")
    context = active_context_from_payload({"cwd": str(root), "session_id": "progress-session"}, resolve_git=False)
    payload = {
        **_payload(root),
        "progress_plan_id": "progress",
        "progress_complete": True,
        "validation_status": "pass",
    }

    result = complete_progress(payload, context)
    assert result.changed is False
    assert result.error_code == "progress_future_schema"
    assert state.read_text(encoding="utf-8") == '{"schema_version": 999}'
    assert [event["kind"] for event in store.read_events("progress")] == ["started"]
