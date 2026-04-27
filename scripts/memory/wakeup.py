#!/usr/bin/env python3
from __future__ import annotations

import argparse

from _memory_common import LAYER_FILES, compact_words, ensure_runtime, read_text


MAX_WAKEUP_WORDS = 1_500


def build_context() -> str:
    root = ensure_runtime()
    sections = ["# Ralph Codex Wakeup", ""]
    for layer, filename in LAYER_FILES.items():
        text = read_text(root / "layers" / filename, limit_chars=2_500).strip()
        sections.extend([f"## {layer}", text or "No content.", ""])
    handoff = read_text(root / "handoffs" / "latest.md", limit_chars=1_500).strip()
    if handoff:
        sections.extend(["## Latest Handoff", handoff, ""])
    return compact_words("\n".join(sections).strip() + "\n", MAX_WAKEUP_WORDS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Print compact Ralph Codex wakeup context.")
    parser.parse_args()
    print(build_context(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
