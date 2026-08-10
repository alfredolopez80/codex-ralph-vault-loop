from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.implementation_store import ImplementationStore, resolve_store_paths_local
from shared.progress_hook import cheap_lookup
from shared.runtime_profile import profile_from_payload
from shared.active_context import active_context_from_payload
from shared.context_delta import CacheClaim

import session_start_dispatch
import user_prompt_dispatch


def _store(root: Path, *, plan_ids: tuple[str, ...] = ("demo",), workspace: str = "workspace") -> ImplementationStore:
    store = ImplementationStore(resolve_store_paths_local(root))
    for index, plan_id in enumerate(plan_ids):
        store.register_plan(
            plan_id,
            plan_path=f".ralph/plans/{plan_id}.md",
            status="active",
            objective="Keep deterministic recovery bounded.",
            phase="verification",
            next_action="Run focused tests.",
            provenance={
                "git": {"workspace_instance_id": workspace, "branch": "main", "commit": ""},
                "writer_session_id": "writer",
                "model_family": "unknown",
                "model_source": "unknown",
                "model_verified": False,
                "origin": "implementation-progress",
                "intent": "progress-maintenance",
            },
            operation_id=f"start-{index}",
        )
    return store


def _session_payload(root: Path, *, source: str, session: str = "session-a", model: str = "gpt-5.6-luna") -> dict[str, object]:
    return {
        "hook_event_name": "SessionStart",
        "source": source,
        "session_id": session,
        "cwd": str(root),
        "primary_repo_root": str(root),
        "workspace_instance_id": "workspace",
        "model": model,
        "branch": "main",
        "sha": "abc123",
    }


def test_session_start_new_store_matrix_is_ledger_owned_and_local_only(monkeypatch, tmp_path: Path) -> None:
    _store(tmp_path)
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    monkeypatch.setattr("shared.active_context.run_git", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("git child")))
    monkeypatch.setattr(session_start_dispatch, "enqueue_maintenance", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("maintenance")))

    startup = session_start_dispatch.run(_session_payload(tmp_path, source="startup"))
    assert startup and "Implementation progress" in startup
    assert session_start_dispatch.run(_session_payload(tmp_path, source="startup")) == ""
    assert session_start_dispatch.run(_session_payload(tmp_path, source="resume"))
    compact = session_start_dispatch.run(_session_payload(tmp_path, source="compact"))
    assert compact and "Implementation progress" in compact
    assert session_start_dispatch.run(_session_payload(tmp_path, source="compact")) == ""
    assert session_start_dispatch.run(_session_payload(tmp_path, source="clear")) == ""
    assert session_start_dispatch.run(_session_payload(tmp_path, source="startup")) == ""
    ledger = tmp_path / ".local-notes" / "ralph" / "implementation" / "context-emissions.jsonl"
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 3


def test_ambiguous_new_store_is_silent_without_legacy_selection(monkeypatch, tmp_path: Path) -> None:
    _store(tmp_path, plan_ids=("one", "two"))
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    output = session_start_dispatch.run(_session_payload(tmp_path, source="startup"))
    assert output == ""
    assert not (tmp_path / ".local-notes" / "ralph" / "implementation" / "context-emissions.jsonl").exists()


@pytest.mark.parametrize(("model", "limit"), [("gpt-5.6-luna", 512), ("gpt-5.6-terra", 192), ("gpt-5.6-sol", 96), ("unverified", 96)])
def test_new_store_capsules_use_model_budget(monkeypatch, tmp_path: Path, model: str, limit: int) -> None:
    _store(tmp_path)
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    output = session_start_dispatch.run(_session_payload(tmp_path, source="startup", session=f"{model}-session", model=model))
    assert len(output.encode("utf-8")) <= limit
    assert "Authority:" in output


def test_user_prompt_claim_precedes_progress_or_history_render(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    payload = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "prompt-session",
        "cwd": str(workspace),
        "model": "gpt-5.6-luna",
        "prompt": "Show implementation progress context",
    }
    order: list[str] = []
    observed: list[object] = []
    monkeypatch.setattr(user_prompt_dispatch, "cheap_lookup", lambda *_args, **_kwargs: type("Lookup", (), {"identity": None, "store": None})())
    monkeypatch.setattr(user_prompt_dispatch, "claim", lambda *_args, **_kwargs: (order.append("claim") or CacheClaim("hit", "unchanged")))
    monkeypatch.setattr(user_prompt_dispatch, "record_event", lambda *_args, **_kwargs: observed.append(True))
    monkeypatch.setattr(user_prompt_dispatch, "_continuity_context", lambda *_args: (_ for _ in ()).throw(AssertionError("rendered before claim")))
    monkeypatch.setattr(user_prompt_dispatch, "read_state", lambda *_args: (_ for _ in ()).throw(AssertionError("state read before claim")))
    monkeypatch.setattr(user_prompt_dispatch, "run_intake", lambda *_args: (_ for _ in ()).throw(AssertionError("recall on hit")))
    assert user_prompt_dispatch.run(payload) == ""
    assert order == ["claim"]
    assert observed == []


def test_repeated_prompt_skips_state_components_and_progress_narrative(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    payload = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "prompt-session",
        "cwd": str(workspace),
        "model": "gpt-5.6-luna",
        "prompt": "Implement the bounded prompt cache",
    }
    calls = {"state": 0, "intake": 0, "continuity": 0}
    state = {"routing": {"route": "local"}}
    monkeypatch.setattr(user_prompt_dispatch, "read_state", lambda *_args: (calls.__setitem__("state", calls["state"] + 1) or state))
    monkeypatch.setattr(user_prompt_dispatch, "run_intake", lambda *_args: (calls.__setitem__("intake", calls["intake"] + 1) or ("Recall", [], "no")))
    monkeypatch.setattr(user_prompt_dispatch, "_continuity_context", lambda *_args: (calls.__setitem__("continuity", calls["continuity"] + 1) or ""))
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    first = user_prompt_dispatch.run(payload)
    assert first
    second = user_prompt_dispatch.run(payload)
    assert second == ""
    assert calls == {"state": 0, "intake": 1, "continuity": 1}
    assert "Latest rolling checkpoint" not in first
    assert "Implementation progress" not in first


def test_repeated_prompt_new_store_hit_skips_full_progress_reads_and_writes(monkeypatch, tmp_path: Path) -> None:
    _store(tmp_path)
    payload = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "prompt-session",
        "cwd": str(tmp_path),
        "primary_repo_root": str(tmp_path),
        "workspace_instance_id": "workspace",
        "model": "gpt-5.6-luna",
        "branch": "main",
        "sha": "abc123",
        "prompt": "Implement the bounded prompt cache",
    }
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    monkeypatch.setattr(user_prompt_dispatch, "run_intake", lambda *_args: ("Recall", [], "no"))
    monkeypatch.setattr(user_prompt_dispatch, "initialize", lambda *_args: {"routing": {"route": "local"}})
    monkeypatch.setattr(user_prompt_dispatch, "record_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ImplementationStore, "read_state", lambda *_args: (_ for _ in ()).throw(AssertionError("full state read")))
    monkeypatch.setattr(ImplementationStore, "read_events", lambda *_args: (_ for _ in ()).throw(AssertionError("journal read")))

    first = user_prompt_dispatch.run(payload)
    assert first
    files_before = {
        path.relative_to(tmp_path): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in tmp_path.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    assert user_prompt_dispatch.run(payload) == ""
    files_after = {
        path.relative_to(tmp_path): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in tmp_path.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    assert files_after == files_before
