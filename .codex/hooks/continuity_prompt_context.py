#!/usr/bin/env python3
from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

from shared.active_context import ActiveContext, active_context_from_payload, project_runtime_root
from shared.checkpoint_io import content_hash as hash_text
from shared.checkpoint_io import checkpoint_is_injectable, checkpoint_paths, load_latest, render_checkpoint, update_checkpoint
from shared.paths import append_jsonl, now_iso, read_hook_input, write_json
from shared.redaction import is_red, safe_preview


CONTINUATION_PHRASES = (
    "continua",
    "sigue",
    "donde quedamos",
    "resume work",
    "resume task",
    "resume session",
    "resume where we left off",
    "ok sigue",
    "continue",
    "carry on",
    "where were we",
    "pick it up",
)
MAX_CONTEXT_WORDS = 300
UNKNOWN_SESSION_ID = "unknown"


def main() -> int:
    payload = read_hook_input()
    prompt = prompt_text(payload)
    if not prompt:
        return 0
    context = active_context_from_payload(payload)
    session_id = context.session_id
    if is_continuation(prompt):
        maybe_inject(session_id, context)
        return 0
    maybe_update_objective(prompt, context)
    return 0


def prompt_text(payload: dict[str, Any]) -> str:
    value = payload.get("prompt") or payload.get("user_prompt") or ""
    return value.strip() if isinstance(value, str) else ""


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.lower().split())


def is_continuation(prompt: str) -> bool:
    normalized = normalize(prompt)
    tokens = set(normalized.split())
    return any(phrase in normalized if " " in phrase else phrase in tokens for phrase in CONTINUATION_PHRASES)


def maybe_update_objective(prompt: str, context: ActiveContext) -> None:
    if is_red(prompt) or not looks_like_new_task(prompt):
        return
    result = update_checkpoint(
        {
            "source": "UserPromptSubmit",
            "session_id": context.session_id,
            "objective": safe_preview(prompt, 240),
            "current_phase": "UserPromptSubmit",
            "next_action": "Continue the user's latest requested task.",
        },
        context=context,
    )
    status = str(result.get("status", ""))
    root = project_runtime_root(context)
    append_jsonl(root / "checkpoints" / "prompt-events.jsonl", {"created_at": now_iso(), "event": "objective_update", "status": status})


def looks_like_new_task(prompt: str) -> bool:
    words = prompt.split()
    if len(words) < 4:
        return False
    if prompt.strip().endswith("?") and not any(marker in normalize(prompt) for marker in ("haz", "crea", "implement", "fix", "revisa")):
        return False
    return True


def maybe_inject(session_id: str, context: ActiveContext) -> None:
    try:
        checkpoint = load_latest(context=context)
    except Exception:
        return
    if not checkpoint or not checkpoint_is_injectable(checkpoint, context):
        return
    content_hash = str(checkpoint.get("content_hash") or "")
    if not content_hash:
        content_hash = hash_text(render_checkpoint(checkpoint))
    has_stable_session = session_id != UNKNOWN_SESSION_ID
    if has_stable_session and already_injected(session_id, content_hash, context):
        return
    rendered = render_checkpoint(checkpoint, max_words=MAX_CONTEXT_WORDS).strip()
    if not rendered or is_red(rendered):
        return
    if has_stable_session:
        record_injection(session_id, content_hash, context)
    write_json(
        {
            "continue": True,
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": "Latest rolling checkpoint:\n" + rendered,
            },
        }
    )


def injection_state_path(context: ActiveContext) -> Path:
    return checkpoint_paths(context=context)["injection_state"]


def read_injection_state(context: ActiveContext) -> dict[str, Any]:
    path = injection_state_path(context)
    if not path.exists():
        return {"sessions": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"sessions": {}}
    return data if isinstance(data, dict) else {"sessions": {}}


def already_injected(session_id: str, content_hash: str, context: ActiveContext) -> bool:
    sessions = read_injection_state(context).get("sessions", {})
    if not isinstance(sessions, dict):
        return False
    state = sessions.get(session_id, {})
    return isinstance(state, dict) and state.get("last_hash") == content_hash


def record_injection(session_id: str, content_hash: str, context: ActiveContext) -> None:
    path = injection_state_path(context)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = read_injection_state(context)
    sessions = data.setdefault("sessions", {})
    if not isinstance(sessions, dict):
        sessions = {}
        data["sessions"] = sessions
    sessions[session_id] = {"last_hash": content_hash, "injected_at": now_iso(), "project_id": context.project_id}
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
