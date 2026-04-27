#!/usr/bin/env python3
from __future__ import annotations

import argparse

from _memory_common import content_hash, ensure_runtime, now_iso, render_frontmatter, slugify
from classify_learning import classify_learning


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract a sanitized learning from a session note.")
    parser.add_argument("--text", required=True)
    parser.add_argument("--classification")
    parser.add_argument("--title", default="session-learning")
    args = parser.parse_args()

    classification = classify_learning(args.text, args.classification)
    digest = content_hash(args.text)
    if classification == "RED":
        print(f"EXTRACT_SESSION_SKIPPED_RED {digest}")
        return 0

    root = ensure_runtime()
    path = root / "ledgers" / f"{slugify(args.title)}-{digest[:12]}.md"
    metadata = {
        "created_at": now_iso(),
        "classification": classification,
        "hash": digest,
        "title": args.title,
    }
    path.write_text(render_frontmatter(metadata) + "\n\n" + args.text.strip() + "\n", encoding="utf-8")
    print(f"EXTRACT_SESSION_OK {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
