#!/usr/bin/env python3
from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

from shared.checkpoint_io import content_hash as hash_text
from shared.checkpoint_io import checkpoint_is_injectable, checkpoint_paths, load_latest, render_checkpoint, update_checkpoint
from shared.paths import append_jsonl, ensure_runtime, now_iso, read_hook_input, write_json
from shared.redaction import is_red, safe_preview


CONTINUATION_PHRASES = (
    "continua",
    "sigue",
    "donde quedamos",
    "resume",
    "ok sigue",
    "continue",
    "carry on",
    "where were we",
    "pick it up",
)
MAX_CONTEXT_WORDS = 300


def main() -> int:
    payload = read_hook_input()
    prompt = prompt_text(payload)
    if not prompt:
        return 0
    session_id = safe_session_id(payload)
    if is_continuation(prompt):
        maybe_inject(session_id)
        return 0
    maybe_update_objective(prompt, session_id)
    return 0


def prompt_text(payload: dict[str, Any]) -> str:
    value = payload.get("prompt") or payload.get("user_prompt") or ""
    return value.strip() if isinstance(value, str) else ""


def safe_session_id(payload: dict[str, Any]) -> str:
    value = payload.get("session_id") or "unknown"
    text = "".join(char if char.isalnum() or char in "._-" else "_" for char in str(value))
    return text.strip("_")[:80] or "unknown"


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.lower().split())


def is_continuation(prompt: str) -> bool:
    normalized = normalize(prompt)
    tokens = set(normalized.split())
    return any(phrase in normalized if " " in phrase else phrase in tokens for phrase in CONTINUATION_PHRASES)


def maybe_update_objective(prompt: str, session_id: str) -> None:
    if is_red(prompt) or not looks_like_new_task(prompt):
        return
    result = update_checkpoint(
        {
            "source": "UserPromptSubmit",
            "session_id": session_id,
            "objective": safe_preview(prompt, 240),
            "current_phase": "UserPromptSubmit",
            "next_action": "Continue the user's latest requested task.",
        }
    )
    status = str(result.get("status", ""))
    root = ensure_runtime()
    append_jsonl(root / "checkpoints" / "prompt-events.jsonl", {"created_at": now_iso(), "event": "objective_update", "status": status})


def looks_like_new_task(prompt: str) -> bool:
    words = prompt.split()
    if len(words) < 4:
        return False
    if prompt.strip().endswith("?") and not any(marker in normalize(prompt) for marker in ("haz", "crea", "implement", "fix", "revisa")):
        return False
    return True


def maybe_inject(session_id: str) -> None:
    try:
        checkpoint = load_latest()
    except Exception:
        return
    if not checkpoint or not checkpoint_is_injectable(checkpoint):
        return
    content_hash = str(checkpoint.get("content_hash") or "")
    if not content_hash:
        content_hash = hash_text(render_checkpoint(checkpoint))
    if already_injected(session_id, content_hash):
        return
    rendered = render_checkpoint(checkpoint, max_words=MAX_CONTEXT_WORDS).strip()
    if not rendered or is_red(rendered):
        return
    record_injection(session_id, content_hash)
    write_json(
        {
            "continue": True,
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": "Latest rolling checkpoint:\n" + rendered,
            },
        }
    )


def injection_state_path() -> Path:
    return checkpoint_paths()["injection_state"]


def read_injection_state() -> dict[str, Any]:
    path = injection_state_path()
    if not path.exists():
        return {"sessions": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"sessions": {}}
    return data if isinstance(data, dict) else {"sessions": {}}


def already_injected(session_id: str, content_hash: str) -> bool:
    sessions = read_injection_state().get("sessions", {})
    if not isinstance(sessions, dict):
        return False
    state = sessions.get(session_id, {})
    return isinstance(state, dict) and state.get("last_hash") == content_hash


def record_injection(session_id: str, content_hash: str) -> None:
    path = injection_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = read_injection_state()
    sessions = data.setdefault("sessions", {})
    if not isinstance(sessions, dict):
        sessions = {}
        data["sessions"] = sessions
    sessions[session_id] = {"last_hash": content_hash, "injected_at": now_iso()}
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
