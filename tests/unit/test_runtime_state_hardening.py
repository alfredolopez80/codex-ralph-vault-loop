from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.active_context import active_context_from_payload
from shared.session_context_cache import state_lock, write_state
from shared.sol_advisor import initialize
from shared.stop_scope import scope_from_payload, state_matches_scope


def test_session_context_cache_rejects_symlink_runtime_root(monkeypatch, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked-runtime"
    linked.symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("RALPH_HOME", str(linked))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    context = active_context_from_payload(
        {"cwd": str(workspace), "session_id": "cache-symlink", "branch": "main", "sha": "abc"},
        resolve_git=False,
    )
    with state_lock(context) as locked:
        assert locked is False
    assert write_state(context, {"schema_version": 1, "sessions": {}}) is False
    assert not list(outside.rglob("state.json"))


def test_sol_state_rejects_symlink_root_and_session_escape(monkeypatch, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked-state"
    linked.symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(linked))
    payload = {
        "cwd": str(tmp_path),
        "session_id": "advisor-symlink",
        "prompt": "Review a bounded architecture migration.",
        "complexity": 8,
    }
    assert initialize(payload)
    assert not list(outside.rglob("sol-advisor.json"))

    safe_root = tmp_path / "safe-state"
    safe_root.mkdir()
    session_link = safe_root / "advisor-symlink"
    session_link.symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(safe_root))
    assert initialize(payload)
    assert not list(outside.rglob("sol-advisor.json"))


def test_stop_scope_accepts_short_and_full_sha_for_the_same_head(tmp_path: Path) -> None:
    full_sha = "abcdef1234567890abcdef1234567890abcdef12"
    scope = scope_from_payload(
        {
            "cwd": str(tmp_path),
            "session_id": "same-head-session",
            "task_signature": "same-head-task",
            "branch": "main",
            "sha": full_sha,
        }
    )
    state = {
        "session_id": "same-head-session",
        "task_signature": "same-head-task",
        "sha": full_sha[:12],
    }
    assert state_matches_scope(state, scope) == (True, "matched")

    state["sha"] = "deadbeefdead"
    assert state_matches_scope(state, scope) == (False, "foreign_head")


def test_stop_scope_keeps_safe_task_identity_and_budget_across_head_changes(tmp_path: Path) -> None:
    base = {
        "cwd": str(tmp_path),
        "session_id": "stable-budget-session",
        "task_signature": "task-safe-identifier",
        "branch": "main",
    }
    first = scope_from_payload({**base, "sha": "111111111111"})
    changed = scope_from_payload({**base, "sha": "222222222222"})
    assert first.task_signature == "task-safe-identifier"
    assert first.scope_key == changed.scope_key
