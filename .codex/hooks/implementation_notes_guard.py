#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from shared.paths import REPO_ROOT, read_hook_input, write_json
from shared.redaction import is_red

ROOT = REPO_ROOT
SCRIPTS_PLANS = ROOT / "scripts" / "plans"
if str(SCRIPTS_PLANS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_PLANS))

from implementation_notes_lib import (  # noqa: E402
    ImplementationNotesError,
    canonical_plan_path,
    ensure_plan_path_allowed,
    is_codex_worktree,
    is_plan_approved,
    notes_has_non_initial_entry,
    parse_plan_metadata,
    read_implementation_plan_state,
    resolve_for_read,
    resolve_notes_path_for_plan,
    resolve_roots,
    safe_session_id,
)
from implementation_index_lib import current_git_metadata, upsert_plan_entry  # noqa: E402


PLAN_PATH_CHARS = r"[^\s`()\[\]]"
MARKDOWN_PLAN_LINK_RE = re.compile(
    rf"\[[^\]\n]*\]\((?P<path>{PLAN_PATH_CHARS}+\.ralph/plans/{PLAN_PATH_CHARS}+\.md)\)"
)


def _message(payload: dict[str, Any]) -> str:
    value = payload.get("last_assistant_message") or payload.get("lastAssistantMessage") or ""
    return value if isinstance(value, str) else ""


def _payload_plan_path(payload: dict[str, Any]) -> tuple[str, str]:
    for key in ("implementation_plan_path", "implementationPlanPath", "plan_path", "planPath"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip(), "payload"
    message = _message(payload)
    match = MARKDOWN_PLAN_LINK_RE.search(message)
    if match:
        return match.group("path"), "markdown"
    return "", ""


def _explicit_approved(payload: dict[str, Any]) -> bool:
    for key in ("plan_approved", "planApproved", "implementation_plan_approved", "implementationPlanApproved"):
        if payload.get(key) is True:
            return True
    return False


def _payload_cwd(payload: dict[str, Any]) -> str:
    for key in ("cwd", "workdir", "working_directory", "workspace_root"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _payload_session_id(payload: dict[str, Any]) -> str:
    for key in ("session_id", "sessionId", "codex_session_id", "codexSessionId"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return safe_session_id(value)
    return "unknown"


def _state_matches_roots(state: dict[str, str], roots: Any) -> bool:
    stored_active = state.get("active_worktree_root", "").strip()
    stored_primary = state.get("primary_repo_root", "").strip()
    if not stored_active or not stored_primary:
        return False
    return Path(stored_active).expanduser().resolve(strict=False) == roots.active_worktree_root.resolve(
        strict=False
    ) and Path(stored_primary).expanduser().resolve(strict=False) == roots.primary_repo_root.resolve(strict=False)


def block(reason: str) -> int:
    write_json({"decision": "block", "reason": reason})
    return 0


def canonical_plan_for_guard(plan_path: Path, roots: Any) -> Path:
    if not is_codex_worktree(plan_path):
        return plan_path
    canonical_plan = canonical_plan_path(plan_path, roots.primary_repo_root)
    if not canonical_plan.exists():
        raise ImplementationNotesError(
            "approved implementation plan exists only in an ephemeral Codex worktree; "
            "copy it to the canonical repo root .ralph/plans/ before finalizing"
        )
    return canonical_plan


def markdown_plan_link_is_in_scope(plan_value: str, roots: Any) -> bool:
    candidate = Path(plan_value).expanduser().resolve(strict=False)
    try:
        ensure_plan_path_allowed(candidate, roots)
    except ImplementationNotesError:
        return False
    return True


def main() -> int:
    payload = read_hook_input()
    if payload.get("stop_hook_active"):
        return 0

    message = _message(payload)
    if message and is_red(message):
        return 0

    try:
        plan_value, plan_source = _payload_plan_path(payload)
        try:
            roots = resolve_roots(_payload_cwd(payload) or Path.cwd())
        except ImplementationNotesError as exc:
            if "not inside a git repository" in str(exc):
                return 0
            raise
        if not plan_value:
            state = read_implementation_plan_state(roots.active_worktree_root, _payload_session_id(payload))
            if state and not _state_matches_roots(state, roots):
                state = {}
            plan_value = state.get("plan_path", "")
            plan_source = "state" if plan_value else ""
        if not plan_value:
            return 0
        if plan_source == "markdown" and not markdown_plan_link_is_in_scope(plan_value, roots):
            return 0
        plan_path = resolve_for_read(plan_value)
        ensure_plan_path_allowed(plan_path, roots)
        plan_path = canonical_plan_for_guard(plan_path, roots)
        ensure_plan_path_allowed(plan_path, roots)
        metadata = parse_plan_metadata(plan_path)
        if not metadata.implementation_notes_required:
            return 0
        if not is_plan_approved(metadata, explicit_approved=_explicit_approved(payload)):
            return block("Implementation notes plan is marked required, but the referenced plan is not approved.")

        notes_path = resolve_notes_path_for_plan(metadata, plan_path, roots.primary_repo_root)
        if not notes_path.exists():
            return block("Plan requires implementation notes, but the notes file was not found.")
        if is_codex_worktree(notes_path):
            return block("Implementation notes path points to an ephemeral Codex worktree.")
        if not notes_has_non_initial_entry(notes_path):
            return block("Implementation notes exist but do not contain any decision entries beyond the initial template.")
        git_meta = current_git_metadata(roots.active_worktree_root)
        upsert_plan_entry(
            primary_root=roots.primary_repo_root,
            plan_path=plan_path,
            notes_path=notes_path,
            status="implemented",
            active_root=roots.active_worktree_root,
            commit=git_meta["commit"],
            branch=git_meta["branch"],
            session_id=_payload_session_id(payload),
        )
        return 0
    except ImplementationNotesError as exc:
        return block(f"Implementation notes guard could not validate plan: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
