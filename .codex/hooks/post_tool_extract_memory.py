#!/usr/bin/env python3
from __future__ import annotations

from shared.paths import read_hook_input
from shared.redaction import safe_preview
from shared.vault_io import save_learning


LEARNING_MARKERS = ("learned", "decision", "fixed", "root cause", "checkpoint", "validated", "pass")


def main() -> int:
    payload = read_hook_input()
    text = " ".join(
        safe_preview(payload.get(key, ""))
        for key in ("output", "output_preview", "outputPreview", "result")
        if payload.get(key)
    )
    if not text.strip():
        return 0
    lowered = text.lower()
    if any(marker in lowered for marker in LEARNING_MARKERS):
        save_learning(text, source="PostToolUse", classification="YELLOW")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
