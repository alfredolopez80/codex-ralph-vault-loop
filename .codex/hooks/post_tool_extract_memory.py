#!/usr/bin/env python3
from __future__ import annotations

from shared.active_context import active_context_from_payload
from shared.learning import learning_text_from_payload, should_persist_learning
from shared.paths import read_hook_input
from shared.redaction import is_red
from shared.vault_io import save_learning


LEARNING_FIELDS = ("output", "output_preview", "outputPreview", "result")


def raw_learning_candidate(payload: dict) -> str:
    return " ".join(str(payload.get(field, "")) for field in LEARNING_FIELDS if payload.get(field))


def main() -> int:
    try:
        payload = read_hook_input()
        raw_text = raw_learning_candidate(payload)
        if not raw_text.strip() or is_red(raw_text) or not should_persist_learning(raw_text):
            return 0
        context = active_context_from_payload(payload)
        text = learning_text_from_payload(payload, LEARNING_FIELDS)
        if text:
            save_learning(text, source="PostToolUse", classification="YELLOW", context=context)
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
