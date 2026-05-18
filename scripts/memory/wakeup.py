#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from _memory_common import LAYER_FILES, compact_words, ensure_runtime, read_text


MAX_WAKEUP_WORDS = 1_500
CHECKPOINT_WAKEUP_WORDS = 500

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / ".codex" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

from shared.checkpoint_io import (  # noqa: E402
    CheckpointError,
    checkpoint_is_injectable,
    checkpoint_paths,
    content_hash,
    load_latest,
    render_checkpoint,
)
from shared.paths import now_iso  # noqa: E402


def build_context() -> str:
    root = ensure_runtime()
    sections = ["# Ralph Codex Wakeup", ""]
    for layer, filename in LAYER_FILES.items():
        text = read_text(root / "layers" / filename, limit_chars=2_500).strip()
        sections.extend([f"## {layer}", text or "No content.", ""])
    handoff = read_text(root / "handoffs" / "latest.md", limit_chars=1_500).strip()
    if handoff:
        sections.extend(["## Latest Handoff", handoff, ""])
    checkpoint = render_checkpoint_for_session(root, max_words=CHECKPOINT_WAKEUP_WORDS)
    if checkpoint:
        sections.extend(["## Latest Rolling Checkpoint", checkpoint, ""])
    return compact_words("\n".join(sections).strip() + "\n", MAX_WAKEUP_WORDS)


def render_checkpoint_for_session(root: Path, max_words: int) -> str:
    try:
        checkpoint = load_latest(root)
    except CheckpointError:
        return ""
    if not checkpoint or not checkpoint_is_injectable(checkpoint):
        return ""
    session_id = current_session_id()
    checkpoint_hash = str(checkpoint.get("content_hash") or "")
    rendered = render_checkpoint(checkpoint, max_words=max_words).strip()
    if not checkpoint_hash:
        checkpoint_hash = content_hash(rendered)
    if session_id and already_injected(root, session_id, checkpoint_hash):
        return ""
    if session_id:
        record_injection(root, session_id, checkpoint_hash)
    return rendered


def current_session_id() -> str:
    value = os.environ.get("CODEX_SESSION_ID") or os.environ.get("RALPH_SESSION_ID") or ""
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in value)
    return safe.strip("_")[:80]


def read_injection_state(root: Path) -> dict[str, Any]:
    path = checkpoint_paths(root)["injection_state"]
    if not path.exists():
        return {"sessions": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"sessions": {}}
    return data if isinstance(data, dict) else {"sessions": {}}


def already_injected(root: Path, session_id: str, checkpoint_hash: str) -> bool:
    sessions = read_injection_state(root).get("sessions", {})
    state = sessions.get(session_id, {}) if isinstance(sessions, dict) else {}
    return isinstance(state, dict) and state.get("last_hash") == checkpoint_hash


def record_injection(root: Path, session_id: str, checkpoint_hash: str) -> None:
    path = checkpoint_paths(root)["injection_state"]
    path.parent.mkdir(parents=True, exist_ok=True)
    data = read_injection_state(root)
    sessions = data.setdefault("sessions", {})
    if not isinstance(sessions, dict):
        sessions = {}
        data["sessions"] = sessions
    sessions[session_id] = {"last_hash": checkpoint_hash, "injected_at": now_iso()}
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Print compact Ralph Codex wakeup context.")
    parser.parse_args()
    print(build_context(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
