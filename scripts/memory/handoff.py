#!/usr/bin/env python3
from __future__ import annotations

import argparse

from _memory_common import ensure_runtime, now_iso, render_frontmatter


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the latest Ralph Codex handoff.")
    parser.add_argument("--summary", required=True)
    parser.add_argument("--status", default="unknown")
    parser.add_argument("--next", default="")
    args = parser.parse_args()

    root = ensure_runtime()
    metadata = {
        "created_at": now_iso(),
        "status": args.status,
        "classification": "YELLOW",
    }
    body = [
        render_frontmatter(metadata),
        "",
        "# Latest Handoff",
        "",
        f"Status: {args.status}",
        "",
        args.summary.strip(),
    ]
    if args.next.strip():
        body.extend(["", "Next:", "", args.next.strip()])
    text = "\n".join(body).rstrip() + "\n"

    latest = root / "handoffs" / "latest.md"
    latest.write_text(text, encoding="utf-8")
    archive = root / "handoffs" / f"{now_iso().replace(':', '').replace('+', 'Z')}.md"
    archive.write_text(text, encoding="utf-8")
    print(f"HANDOFF_OK {latest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
