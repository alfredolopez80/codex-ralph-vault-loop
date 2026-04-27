#!/usr/bin/env python3
from __future__ import annotations

from shared.paths import append_jsonl, ensure_runtime, now_iso, read_hook_input
from shared.redaction import is_red, safe_preview


def main() -> int:
    payload = read_hook_input()
    prompt = payload.get("prompt") or payload.get("user_prompt") or ""
    if not isinstance(prompt, str) or not prompt.strip() or is_red(prompt):
        return 0

    root = ensure_runtime()
    append_jsonl(
        root / "ledgers" / "user-prompts.jsonl",
        {
            "created_at": now_iso(),
            "event": "UserPromptSubmit",
            "prompt": safe_preview(prompt),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
