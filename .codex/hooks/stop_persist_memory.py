#!/usr/bin/env python3
from __future__ import annotations

from shared.paths import read_hook_input
from shared.redaction import is_red, safe_preview
from shared.vault_io import write_handoff


def main() -> int:
    payload = read_hook_input()
    if payload.get("stop_hook_active"):
        return 0
    message = payload.get("last_assistant_message") or payload.get("lastAssistantMessage") or ""
    if not isinstance(message, str) or not message.strip():
        return 0
    if is_red(message):
        return 0
    write_handoff(safe_preview(message, limit=2_000), status="stop-hook")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
