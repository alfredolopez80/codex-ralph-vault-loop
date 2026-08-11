from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

import shared.convergence_authority as authority_module  # noqa: E402
from shared.convergence_authority import AuthorityError, ensure_prompt_boundary, load_authoritative_state  # noqa: E402
from shared.convergent_contracts import TaskIdentity, new_state  # noqa: E402
from shared.execution_policy import load_execution_policy  # noqa: E402


def test_off_rollback_is_non_mutating_without_an_active_plan(tmp_path: Path) -> None:
    result = ensure_prompt_boundary(
        {"cwd": str(tmp_path), "session_id": "session-a", "prompt": "implement the change"},
        prompt="implement the change",
        boundary={"boundary_kind": "new_task", "risk": "low", "complexity": 1},
        mode="off",
    )
    assert result is None


def test_retired_shadow_mode_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(AuthorityError, match="activation-mode-invalid"):
        ensure_prompt_boundary(
            {"cwd": str(tmp_path), "session_id": "session-a", "prompt": "implement the change"},
            prompt="implement the change",
            boundary={"boundary_kind": "new-task", "risk": "low", "complexity": 1},
            mode="shadow",
        )


def test_enforce_never_uses_a_caller_snapshot_without_canonical_state(tmp_path: Path) -> None:
    payload = {
        "cwd": str(tmp_path),
        "session_id": "session-a",
        "task_signature": "task-a",
        "convergence_state": {"schema_version": 3, "status": "closed"},
    }
    with pytest.raises(AuthorityError, match="convergent-(authority|state)-"):
        load_authoritative_state(payload)


def test_repeated_new_task_boundary_for_same_work_item_is_idempotent(monkeypatch, tmp_path: Path) -> None:
    policy = load_execution_policy()
    identity = TaskIdentity.from_values(
        session="writer-session",
        project="project",
        worktree=str(tmp_path),
        branch="codex/ralph-convergent-execution-v4",
        objective="same work item",
        boundary_epoch=1,
        sensitivity="GREEN",
        plan="fixture-plan",
        plan_version=1,
        plan_digest="sha256:" + "a" * 64,
    )
    state = new_state(
        policy=policy,
        plan_id="fixture-plan",
        plan_version=1,
        plan_digest="sha256:" + "a" * 64,
        task_identity=identity,
        goal_id="G-BASELINE",
        task_epoch="epoch-1",
        boundary_epoch=1,
        boundary_kind="new_task",
        activation_mode="enforce",
    )
    authority = SimpleNamespace(
        active=SimpleNamespace(
            session_id="new-session",
            project_id="project",
            workspace_root=tmp_path,
            branch="codex/ralph-convergent-execution-v4",
        ),
        policy=policy,
        plan_id="fixture-plan",
        plan_version=1,
        plan_digest="sha256:" + "a" * 64,
        store=SimpleNamespace(read_current=lambda _plan_id: SimpleNamespace(state=state)),
    )
    monkeypatch.setattr(authority_module, "resolve_authority", lambda _payload: authority)
    monkeypatch.setattr(authority_module, "_validate_binding", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        authority_module,
        "_require_runtime_attestation",
        lambda _authority: SimpleNamespace(lease_evidence=lambda **_kwargs: object()),
    )
    monkeypatch.setattr(authority_module, "acquire_execution_lease", lambda *args, **kwargs: object())
    rotate_calls: list[object] = []
    monkeypatch.setattr(
        authority.store,
        "rotate_epoch_and_transition",
        lambda *args, **kwargs: rotate_calls.append((args, kwargs)),
        raising=False,
    )

    result = ensure_prompt_boundary(
        {
            "cwd": str(tmp_path),
            "session_id": "new-session",
            "objective": "same work item",
        },
        prompt="same work item",
        boundary={"boundary_kind": "new_task", "risk": "low", "complexity": 1},
        mode="enforce",
    )

    assert result == state
    assert rotate_calls == []


def test_caller_epoch_label_cannot_bypass_same_work_retry_guard(monkeypatch, tmp_path: Path) -> None:
    policy = load_execution_policy()
    identity = TaskIdentity.from_values(
        session="writer-session",
        project="project",
        worktree=str(tmp_path),
        branch="codex/ralph-convergent-execution-v4",
        objective="same work item",
        boundary_epoch=1,
        sensitivity="GREEN",
        plan="fixture-plan",
        plan_version=1,
        plan_digest="sha256:" + "a" * 64,
    )
    state = new_state(
        policy=policy,
        plan_id="fixture-plan",
        plan_version=1,
        plan_digest="sha256:" + "a" * 64,
        task_identity=identity,
        goal_id="G-BASELINE",
        task_epoch="epoch-1",
        boundary_epoch=1,
        boundary_kind="new_task",
        activation_mode="enforce",
    )
    authority = SimpleNamespace(
        active=SimpleNamespace(
            session_id="new-session",
            project_id="project",
            workspace_root=tmp_path,
            branch="codex/ralph-convergent-execution-v4",
        ),
        policy=policy,
        plan_id="fixture-plan",
        plan_version=1,
        plan_digest="sha256:" + "a" * 64,
        store=SimpleNamespace(read_current=lambda _plan_id: SimpleNamespace(state=state)),
    )
    monkeypatch.setattr(authority_module, "resolve_authority", lambda _payload: authority)
    monkeypatch.setattr(authority_module, "_validate_binding", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(authority_module, "_require_runtime_attestation", lambda _authority: object())
    rotate_calls: list[object] = []
    monkeypatch.setattr(
        authority.store,
        "rotate_epoch_and_transition",
        lambda *args, **kwargs: rotate_calls.append((args, kwargs)) or SimpleNamespace(state=args[0]),
        raising=False,
    )

    result = ensure_prompt_boundary(
        {
            "cwd": str(tmp_path),
            "session_id": "new-session",
            "objective": "same work item",
            "task_epoch": "epoch-2",
        },
        prompt="same work item",
        boundary={"boundary_kind": "new_task", "risk": "low", "complexity": 1},
        mode="enforce",
    )

    assert result == state
    assert rotate_calls == []


@pytest.mark.parametrize("boundary_kind", ["continuation", "new_task"])
def test_risky_same_work_boundary_requires_amendment_before_state_reuse(
    monkeypatch, tmp_path: Path, boundary_kind: str
) -> None:
    policy = load_execution_policy()
    identity = TaskIdentity.from_values(
        session="writer-session",
        project="project",
        worktree=str(tmp_path),
        branch="codex/ralph-convergent-execution-v4",
        objective="same work item",
        boundary_epoch=1,
        sensitivity="GREEN",
        plan="fixture-plan",
        plan_version=1,
        plan_digest="sha256:" + "a" * 64,
    )
    state = new_state(
        policy=policy,
        plan_id="fixture-plan",
        plan_version=1,
        plan_digest="sha256:" + "a" * 64,
        task_identity=identity,
        goal_id="G-BASELINE",
        task_epoch="epoch-1",
        boundary_epoch=1,
        boundary_kind="new_task",
        risk="low",
        activation_mode="enforce",
    )
    authority = SimpleNamespace(
        active=SimpleNamespace(
            session_id="writer-session",
            project_id="project",
            workspace_root=tmp_path,
            branch="codex/ralph-convergent-execution-v4",
        ),
        policy=policy,
        plan_id="fixture-plan",
        plan_version=1,
        plan_digest="sha256:" + "a" * 64,
        store=SimpleNamespace(read_current=lambda _plan_id: SimpleNamespace(state=state)),
    )
    monkeypatch.setattr(authority_module, "resolve_authority", lambda _payload: authority)
    monkeypatch.setattr(authority_module, "_validate_binding", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(authority_module, "_require_runtime_attestation", lambda _authority: object())

    with pytest.raises(AuthorityError, match="amendment-required"):
        ensure_prompt_boundary(
            {"cwd": str(tmp_path), "session_id": "writer-session", "objective": "same work item"},
            prompt="continue with expanded approval scope",
            boundary={
                "boundary_kind": boundary_kind,
                "risk": "material",
                "complexity": 4,
                "scope_delta": True,
            },
            mode="enforce",
        )


def test_git_sha_matching_accepts_sha256_and_rejects_non_prefixes() -> None:
    actual = "a" * 64
    assert authority_module._sha_matches(actual, actual)
    assert authority_module._sha_matches(actual[:12], actual)
    assert not authority_module._sha_matches("b" * 64, actual)
