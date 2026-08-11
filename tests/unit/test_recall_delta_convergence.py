from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".codex" / "hooks"))

from shared.recall_delta import (  # noqa: E402
    RecallDeltaError,
    RecallKey,
    compute_delta,
    prepare_selection,
)


def key(*, epoch: str = "ctx-1", memory: int = 1, checkpoint: int = 1, selection: str = "") -> RecallKey:
    return RecallKey.create(
        project_id="project-1",
        worktree_id="worktree-1",
        branch="codex/v4",
        task_id="task-1",
        memory_generation=memory,
        checkpoint_generation=checkpoint,
        selection_fingerprint=selection,
        context_epoch=epoch,
    )


def test_unchanged_selection_is_zero_read_zero_write_and_head_is_not_hot_key() -> None:
    current = key()
    hit = compute_delta(current, current, selected_ids=["M-1"], previous_selected_ids=["M-1"])
    assert hit.mode == "hit"
    assert hit.body_reads == 0
    assert hit.durable_writes == 0
    assert hit.additional_context == ""
    assert key().hot_fingerprint == current.hot_fingerprint


def test_context_epoch_change_is_one_bounded_rehydration() -> None:
    result = compute_delta(key(), key(epoch="ctx-2"), selected_ids=["M-1"], previous_selected_ids=["M-1"])
    assert result.mode == "rehydrate"
    assert result.body_reads == 1
    assert result.durable_writes == 0
    assert result.additional_context == ""


def test_selection_change_emits_only_new_ids_and_never_bodies() -> None:
    result = compute_delta(
        key(),
        key(selection="sha256:" + "1" * 64),
        selected_ids=["M-1", "M-2"],
        previous_selected_ids=["M-1"],
        selection_changed=True,
    )
    assert result.mode == "delta"
    assert result.delta_ids == ("M-2",)
    assert result.body_reads == 1
    assert result.additional_context == ""


def test_selection_filters_red_stale_wrong_scope_and_conflicting_rows() -> None:
    selected, fingerprint = prepare_selection(
        [
            {"id": "M-good", "project_id": "project-1", "worktree_id": "worktree-1", "branch": "codex/v4"},
            {"id": "M-red", "sensitivity": "RED"},
            {"id": "M-stale", "status": "stale"},
            {"id": "M-wrong", "project_id": "other"},
            {"id": "M-conflict", "status": "conflicting"},
        ],
        project_id="project-1",
        worktree_id="worktree-1",
        branch="codex/v4",
    )
    assert selected == ("M-good",)
    assert fingerprint.startswith("sha256:")


def test_wrong_scope_and_unsafe_selection_block_without_reads() -> None:
    result = compute_delta(key(), RecallKey.create(
        project_id="other",
        worktree_id="worktree-1",
        branch="codex/v4",
        task_id="task-1",
        memory_generation=1,
        checkpoint_generation=1,
        selection_fingerprint="",
        context_epoch="ctx-1",
    ), selected_ids=[])
    assert result.mode == "reject"
    assert result.body_reads == 0
    with pytest.raises(RecallDeltaError):
        RecallKey.create(
            project_id="project-1",
            worktree_id="worktree-1",
            branch="codex/v4",
            task_id="task-1",
            memory_generation=0,
            checkpoint_generation=0,
            selection_fingerprint="not-a-digest",
            context_epoch="ctx-1",
        )


def test_generation_only_change_keeps_same_epoch_selection_on_zero_read_hit() -> None:
    previous = key(memory=1, checkpoint=3, selection="sha256:" + "a" * 64)
    current = key(memory=2, checkpoint=4, selection="sha256:" + "a" * 64)
    result = compute_delta(
        previous,
        current,
        selected_ids=["M-1"],
        previous_selected_ids=["M-1"],
    )
    assert result.mode == "hit"
    assert result.reason == "unchanged_same_context_epoch"
    assert result.body_reads == 0
    assert result.additional_context == ""
    assert result.durable_writes == 0


def test_metadata_rows_with_raw_fields_are_not_selected() -> None:
    selected, _fingerprint = prepare_selection(
        [
            {"id": "M-body", "body": "must not enter recall"},
            {"id": "M-content", "content": "must not enter recall"},
            {"id": "M-good", "title": "bounded metadata"},
        ],
        project_id="project-1",
        worktree_id="worktree-1",
        branch="codex/v4",
    )
    assert selected == ("M-good",)
