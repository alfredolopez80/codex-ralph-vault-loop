"""Pure metadata-first Recall Delta contract for Convergent Execution v4.

The hot key deliberately contains only bounded identity and generation
metadata.  This module never opens a memory body and never returns raw memory
content.  Callers may use ``body_reads`` as an obligation for a bounded
rehydration on a cache miss, while unchanged selections remain a physical
no-op.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .convergent_contracts import digest_value
from .redaction import is_red


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,179}$")
_DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
_REJECTED_STATUSES = frozenset({"red", "stale", "deprecated", "conflicting", "wrong_scope", "oversized"})
MAX_SELECTED_IDS = 64
_FORBIDDEN_METADATA_KEYS = frozenset(
    {"prompt", "raw_prompt", "body", "content", "stdout", "stderr", "log", "reviewer_output", "secret", "token", "credential"}
)


class RecallDeltaError(ValueError):
    """Raised when recall metadata is unsafe or outside the v4 contract."""


@dataclass(frozen=True)
class RecallKey:
    project_id: str
    worktree_id: str
    branch: str
    task_id: str
    memory_generation: int
    checkpoint_generation: int
    selection_fingerprint: str
    context_epoch: str

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        worktree_id: str,
        branch: str,
        task_id: str,
        memory_generation: int,
        checkpoint_generation: int,
        selection_fingerprint: str,
        context_epoch: str,
    ) -> "RecallKey":
        for label, value in (
            ("project_id", project_id),
            ("worktree_id", worktree_id),
            ("branch", branch),
            ("task_id", task_id),
            ("context_epoch", context_epoch),
        ):
            _bounded_id(value, label)
        _nonnegative(memory_generation, "memory_generation")
        _nonnegative(checkpoint_generation, "checkpoint_generation")
        if selection_fingerprint and not _DIGEST_RE.fullmatch(selection_fingerprint):
            raise RecallDeltaError("selection_fingerprint must be a sha256 digest")
        return cls(
            project_id=project_id,
            worktree_id=worktree_id,
            branch=branch,
            task_id=task_id,
            memory_generation=memory_generation,
            checkpoint_generation=checkpoint_generation,
            selection_fingerprint=selection_fingerprint,
            context_epoch=context_epoch,
        )

    @property
    def hot_fingerprint(self) -> str:
        """Stable key for selection cache; HEAD is intentionally absent."""

        return digest_value(
            {
                "project_id": self.project_id,
                "worktree_id": self.worktree_id,
                "branch": self.branch,
                "task_id": self.task_id,
                "memory_generation": self.memory_generation,
                "checkpoint_generation": self.checkpoint_generation,
                "selection_fingerprint": self.selection_fingerprint,
                "context_epoch": self.context_epoch,
            }
        )


@dataclass(frozen=True)
class RecallDelta:
    mode: str
    reason: str
    selected_ids: tuple[str, ...]
    delta_ids: tuple[str, ...]
    body_reads: int
    additional_context: str
    durable_writes: int
    cache_key: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "reason": self.reason,
            "selected_ids": list(self.selected_ids),
            "delta_ids": list(self.delta_ids),
            "body_reads": self.body_reads,
            "additional_context": self.additional_context,
            "durable_writes": self.durable_writes,
            "cache_key": self.cache_key,
        }


def prepare_selection(
    rows: Sequence[Mapping[str, object]],
    *,
    project_id: str,
    worktree_id: str,
    branch: str,
    max_items: int = MAX_SELECTED_IDS,
) -> tuple[tuple[str, ...], str]:
    """Select only scoped, non-RED metadata and return IDs plus a digest.

    Bodies are intentionally not accepted as a field and are never read.  A
    row with a rejected status is omitted rather than injected as context.
    """

    _bounded_id(project_id, "project_id")
    _bounded_id(worktree_id, "worktree_id")
    _bounded_id(branch, "branch")
    if not isinstance(max_items, int) or isinstance(max_items, bool) or not 1 <= max_items <= MAX_SELECTED_IDS:
        raise RecallDeltaError("max_items is outside the bounded selection limit")
    selected: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        # Metadata-first recall never accepts a row carrying a body or other
        # raw/sensitive field, even when the field is empty.  The producer
        # must omit those fields before they reach the selection index.
        if _FORBIDDEN_METADATA_KEYS.intersection(row):
            continue
        identifier = row.get("id") or row.get("memory_id")
        if not isinstance(identifier, str) or not _ID_RE.fullmatch(identifier) or is_red(identifier):
            continue
        status = str(row.get("status") or "selected").strip().lower()
        if status in _REJECTED_STATUSES:
            continue
        row_project = str(row.get("project_id") or project_id)
        row_worktree = str(row.get("worktree_id") or worktree_id)
        row_branch = str(row.get("branch") or branch)
        if (row_project, row_worktree, row_branch) != (project_id, worktree_id, branch):
            continue
        sensitivity = str(row.get("sensitivity") or "GREEN").upper()
        if sensitivity == "RED" or any(is_red(str(row.get(field) or "")) for field in ("title", "summary")):
            continue
        if identifier not in selected:
            selected.append(identifier)
        if len(selected) >= max_items:
            break
    fingerprint = digest_value(selected)
    return tuple(selected), fingerprint


def compute_delta(
    previous: RecallKey | None,
    current: RecallKey,
    *,
    selected_ids: Sequence[str] = (),
    previous_selected_ids: Sequence[str] = (),
    selection_changed: bool = False,
    explicit_recall: bool = False,
) -> RecallDelta:
    """Compute a bounded delta without reading or injecting memory bodies."""

    selected = _ids(selected_ids, "selected_ids")
    previous_selected = _ids(previous_selected_ids, "previous_selected_ids")
    if previous is not None and not _same_scope(previous, current):
        return RecallDelta("reject", "wrong_project_branch_or_worktree", selected, (), 0, "", 0, current.hot_fingerprint)
    same_selection = (
        not selection_changed
        and previous is not None
        and previous.selection_fingerprint == current.selection_fingerprint
        and selected == previous_selected
    )
    if previous is not None and not explicit_recall and same_selection and previous.context_epoch == current.context_epoch:
        return RecallDelta("hit", "unchanged_same_context_epoch", selected, (), 0, "", 0, current.hot_fingerprint)
    if previous is not None and not explicit_recall and not selection_changed and previous.context_epoch != current.context_epoch:
        # A changed context epoch needs one bounded rehydration.  The caller
        # is responsible for a bounded body operation; this function emits no
        # body or prompt text.
        return RecallDelta("rehydrate", "context_epoch_changed", selected, (), 1, "", 0, current.hot_fingerprint)
    delta = tuple(item for item in selected if item not in previous_selected)
    return RecallDelta("delta", "selection_changed" if selection_changed else "explicit_recall", selected, delta, len(delta), "", 0, current.hot_fingerprint)


def _same_scope(left: RecallKey, right: RecallKey) -> bool:
    return (left.project_id, left.worktree_id, left.branch, left.task_id) == (
        right.project_id,
        right.worktree_id,
        right.branch,
        right.task_id,
    )


def _ids(values: Sequence[str], label: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)) or len(values) > MAX_SELECTED_IDS:
        raise RecallDeltaError(f"{label} is outside the bounded selection limit")
    result: list[str] = []
    for value in values:
        _bounded_id(value, f"{label} item")
        if value not in result:
            result.append(value)
    return tuple(result)


def _bounded_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value) or is_red(value):
        raise RecallDeltaError(f"{label} is not a safe bounded identifier")
    return value


def _nonnegative(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RecallDeltaError(f"{label} must be nonnegative")


__all__ = ["MAX_SELECTED_IDS", "RecallDelta", "RecallDeltaError", "RecallKey", "compute_delta", "prepare_selection"]
