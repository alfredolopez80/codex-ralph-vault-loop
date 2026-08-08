from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.active_context import ActiveContext, active_context_from_payload, project_runtime_root
from shared.checkpoint_io import update_checkpoint
from shared.session_context_cache import state_path
from shared.vault_io import write_handoff
from session_start_dispatch import run


def context_for(tmp_path: Path, session_id: str = "session-a", branch: str = "main", sha: str = "abc123") -> ActiveContext:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    return active_context_from_payload(
        {"cwd": str(workspace), "session_id": session_id, "branch": branch, "sha": sha},
        resolve_git=False,
    )


def payload(context: ActiveContext, source: str, *, model: str = "gpt-5.6-luna", **extra: object) -> dict[str, object]:
    return {
        "hook_event_name": "SessionStart",
        "source": source,
        "session_id": context.session_id,
        "cwd": str(context.workspace_root),
        "branch": context.branch,
        "sha": context.sha,
        "model": model,
        **extra,
    }


def seed_checkpoint(context: ActiveContext, *, objective: str = "Keep the compact continuity contract green.") -> None:
    update_checkpoint(
        {
            "source": "manual",
            "session_id": context.session_id,
            "objective": objective,
            "current_phase": "Phase 11",
            "next_action": "Run the focused continuity tests.",
            "active_files": [".codex/hooks/session_start_dispatch.py", "tests/unit/test_session_start_dispatch.py"],
            "validation_status": "not_run",
        },
        context=context,
    )


def seed_handoff(context: ActiveContext, text: str = "Decision: preserve only scoped continuity and pending validation.") -> None:
    write_handoff(f"## Current goal\n\n{text}\n\n## Next actions\n\n- Continue the focused validation.", context=context)


def test_startup_without_state_is_silent_and_does_not_spawn(monkeypatch, tmp_path: Path) -> None:
    context = context_for(tmp_path)

    def fail_git(*_args, **_kwargs):
        raise AssertionError("fast SessionStart must not resolve git through a child process")

    monkeypatch.setattr("shared.active_context.run_git", fail_git)
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    assert run(payload(context, "startup")) == ""


def test_startup_emits_scoped_handoff_and_stays_within_luna_budget(monkeypatch, tmp_path: Path) -> None:
    context = context_for(tmp_path)
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    seed_checkpoint(context)
    seed_handoff(context)
    output = run(payload(context, "startup"))
    assert "project=" in output
    assert "objective=" in output
    assert "handoff_next=Continue the focused validation." in output
    assert len(output.encode("utf-8")) <= 2_200
    assert "L0 Identity" not in output
    assert "RED content stays local" not in output


def test_resume_same_fingerprint_is_silent_and_changed_checkpoint_is_delta(monkeypatch, tmp_path: Path) -> None:
    context = context_for(tmp_path)
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    seed_checkpoint(context)
    first = run(payload(context, "startup"))
    assert first
    assert run(payload(context, "resume")) == ""
    update_checkpoint(
        {"source": "manual", "session_id": context.session_id, "next_action": "Run the changed validation command."},
        context=context,
    )
    delta = run(payload(context, "resume"))
    assert "source=resume" in delta
    assert "next=Run the changed validation command." in delta
    assert "L0 Identity" not in delta


def test_clear_does_not_reinject_old_continuity_but_keeps_explicit_ids(monkeypatch, tmp_path: Path) -> None:
    context = context_for(tmp_path)
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    seed_checkpoint(context)
    assert run(payload(context, "startup"))
    assert run(payload(context, "clear")) == ""
    assert run(payload(context, "startup")) == ""
    explicit = run(payload(context, "compact", selected_memory_ids=["sentinel-green-id"]))
    assert "objective=" not in explicit
    assert "memory_ids=sentinel-green-id" in explicit


def test_compact_restores_only_objective_files_validation_and_memory_ids(monkeypatch, tmp_path: Path) -> None:
    context = context_for(tmp_path)
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    seed_checkpoint(context, objective="Restore the current objective after compact.")
    output = run(payload(context, "compact", selected_memory_ids=["green-1", "green-2"]))
    assert "source=compact" in output
    assert "objective=Restore the current objective after compact." in output
    assert "files_in_progress=" in output
    assert "validation_pending=not_run" in output
    assert "memory_ids=green-1; green-2" in output
    assert "Decision: preserve only scoped continuity" not in output
    assert len(output.encode("utf-8")) <= 2_200
    assert run(payload(context, "compact", selected_memory_ids=["green-1", "green-2"])) == ""


def test_sol_profile_hard_cap_and_unknown_profile(monkeypatch, tmp_path: Path) -> None:
    context = context_for(tmp_path)
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    seed_checkpoint(context, objective="á" * 4_000)
    sol_output = run(payload(context, "compact", model="gpt-5.6-sol", selected_memory_ids=["sol-id"]))
    assert len(sol_output.encode("utf-8")) <= 800
    unknown_output = run(payload(context, "compact", model="unrecognized-model", selected_memory_ids=["unknown-id"]))
    assert len(unknown_output.encode("utf-8")) <= 2_200


def test_branch_mismatch_and_stale_handoff_are_never_authoritative(monkeypatch, tmp_path: Path) -> None:
    context = context_for(tmp_path, branch="main", sha="abc123")
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    seed_handoff(context, "BRANCH_SCOPED_SENTINEL")
    handoff_path = project_runtime_root(context) / "handoffs" / "latest.md"
    handoff_path.write_text(handoff_path.read_text(encoding="utf-8").replace('branch: "main"', 'branch: "old-branch"'), encoding="utf-8")
    foreign = run(payload(context, "startup", branch="main", sha="def456"))
    assert "BRANCH_SCOPED_SENTINEL" not in foreign
    assert "ignored_scope" in foreign or foreign == ""
    handoff_path.write_text(
        handoff_path.read_text(encoding="utf-8").replace('created_at: "', 'created_at: "2000-01-01T00:00:00+00:00" # '),
        encoding="utf-8",
    )
    stale = run(payload(context, "startup", branch="main", sha="abc123"))
    assert "BRANCH_SCOPED_SENTINEL" not in stale


def test_corrupt_state_and_red_handoff_fail_open_without_raw_content(monkeypatch, tmp_path: Path) -> None:
    context = context_for(tmp_path)
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    path = state_path(context)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")
    seed_handoff(context, "RAW_RED_SENTINEL")
    handoff_path = project_runtime_root(context) / "handoffs" / "latest.md"
    handoff_path.write_text(handoff_path.read_text(encoding="utf-8").replace('classification: "YELLOW"', 'classification: "RED"'), encoding="utf-8")
    output = run(payload(context, "startup"))
    assert "RAW_RED_SENTINEL" not in output
    assert "not-json" not in json.dumps(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else True
    assert list(path.parent.glob("state.invalid.*.json"))


def test_utf8_output_is_valid_and_cache_contains_no_raw_body(monkeypatch, tmp_path: Path) -> None:
    context = context_for(tmp_path)
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    seed_checkpoint(context, objective="Continuidad segura: " + "ñ" * 2_000)
    output = run(payload(context, "startup"))
    output.encode("utf-8").decode("utf-8")
    assert len(output.encode("utf-8")) <= 2_200
    cached = state_path(context).read_text(encoding="utf-8")
    assert "Continuidad segura" not in cached
    assert "ñ" not in cached
