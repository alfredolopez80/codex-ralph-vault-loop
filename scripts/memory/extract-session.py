#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from _memory_common import atomic_write_text, content_hash, ensure_runtime, now_iso, render_frontmatter, slugify
from classify_learning import classify_learning
from user_memory import main as user_memory_main


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract a sanitized learning from a session note.")
    parser.add_argument("--text", required=True)
    parser.add_argument("--classification")
    parser.add_argument("--title", default="session-learning")
    parser.add_argument(
        "--user-authorized",
        action="store_true",
        help="Persist an explicit user-requested GREEN memory as a recall-visible global note.",
    )
    parser.add_argument("--scope", choices=("repo", "global"), default="repo")
    parser.add_argument("--authoritative", action="store_true")
    args = parser.parse_args()

    if args.user_authorized:
        gateway_args = [
            "user_memory.py", "remember", "--text", args.text, "--scope", args.scope,
        ]
        if args.classification:
            gateway_args.extend(["--classification", args.classification])
        if args.authoritative:
            gateway_args.append("--authoritative")
        previous_argv = sys.argv
        try:
            sys.argv = gateway_args
            return user_memory_main()
        finally:
            sys.argv = previous_argv

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
    atomic_write_text(path, render_frontmatter(metadata) + "\n\n" + args.text.strip() + "\n")
    print(f"EXTRACT_SESSION_OK {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
