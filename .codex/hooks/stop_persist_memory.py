#!/usr/bin/env python3
from __future__ import annotations

from shared.learning import should_persist_learning
from shared.paths import read_hook_input
from shared.redaction import is_red, safe_preview
from shared.vault_io import save_learning, write_handoff


def main() -> int:
    payload = read_hook_input()
    if payload.get("stop_hook_active"):
        return 0
    message = payload.get("last_assistant_message") or payload.get("lastAssistantMessage") or ""
    if not isinstance(message, str) or not message.strip():
        return 0
    if is_red(message):
        return 0
    text = safe_preview(message, limit=2_000)
    write_handoff(text, status="stop-hook")
    if should_persist_learning(text):
        save_learning(text, source="Stop", classification="YELLOW")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
