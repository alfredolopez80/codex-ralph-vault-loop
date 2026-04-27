#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from _memory_common import ensure_runtime, read_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote sanitized ledger notes into L2 project rules.")
    parser.add_argument("--source", help="Optional source note. Defaults to all ledgers.")
    parser.add_argument("--rule", action="append", default=[], help="Rule text to append directly.")
    args = parser.parse_args()

    root = ensure_runtime()
    layer = root / "layers" / "L2_project_rules.md"
    additions: list[str] = []

    if args.source:
        source = Path(args.source).expanduser()
        if not source.is_absolute():
            source = root / args.source
        if source.exists():
            additions.append(read_text(source).strip())
    elif not args.rule:
        for path in sorted((root / "ledgers").glob("*.md")):
            text = read_text(path).strip()
            if 'classification: "RED"' not in text:
                additions.append(text)

    additions.extend(item.strip() for item in args.rule if item.strip())
    if not additions:
        print("GRADUATE_RULES_NOOP")
        return 0

    current = read_text(layer).rstrip()
    with layer.open("w", encoding="utf-8") as handle:
        handle.write(current + "\n\n## Graduated Rules\n\n")
        for item in additions:
            handle.write(item + "\n\n")
    print(f"GRADUATE_RULES_OK {layer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
