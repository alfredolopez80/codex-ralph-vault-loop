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


PLAN_RE = re.compile(r"(?P<path>(?:/[^\s`]+|\.\.?/[^\s`]+)[^\s`]*\.ralph/plans/[^\s`]+\.md)")


def _message(payload: dict[str, Any]) -> str:
    value = payload.get("last_assistant_message") or payload.get("lastAssistantMessage") or ""
    return value if isinstance(value, str) else ""


def _payload_plan_path(payload: dict[str, Any]) -> str:
    for key in ("implementation_plan_path", "implementationPlanPath", "plan_path", "planPath"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    message = _message(payload)
    match = PLAN_RE.search(message)
    return match.group("path") if match else ""


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


def block(reason: str) -> int:
    write_json({"decision": "block", "reason": reason})
    return 0


def main() -> int:
    payload = read_hook_input()
    if payload.get("stop_hook_active"):
        return 0

    message = _message(payload)
    if message and is_red(message):
        return 0

    try:
        roots = resolve_roots(_payload_cwd(payload) or Path.cwd())
        plan_value = _payload_plan_path(payload)
        if not plan_value:
            state = read_implementation_plan_state(roots.active_worktree_root, _payload_session_id(payload))
            plan_value = state.get("plan_path", "")
        if not plan_value:
            return 0
        plan_path = resolve_for_read(plan_value)
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
        return 0
    except ImplementationNotesError as exc:
        return block(f"Implementation notes guard could not validate plan: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
