#!/usr/bin/env python3
from __future__ import annotations

from shared.active_context import active_context_from_payload
from shared.learning import learning_text_from_payload
from shared.paths import read_hook_input
from shared.vault_io import save_learning


LEARNING_FIELDS = ("output", "output_preview", "outputPreview", "result")


def main() -> int:
    try:
        payload = read_hook_input()
        context = active_context_from_payload(payload)
        text = learning_text_from_payload(payload, LEARNING_FIELDS)
        if text:
            save_learning(text, source="PostToolUse", classification="YELLOW", context=context)
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
