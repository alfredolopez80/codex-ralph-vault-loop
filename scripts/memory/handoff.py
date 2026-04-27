#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys

from _memory_common import ensure_runtime, now_iso, render_frontmatter
from classify_learning import classify_learning


MAX_HOOK_SUMMARY_CHARS = 2_000


def write_handoff(summary: str, status: str, next_step: str = ""):
    root = ensure_runtime()
    metadata = {
        "created_at": now_iso(),
        "status": status,
        "classification": "YELLOW",
    }
    body = [
        render_frontmatter(metadata),
        "",
        "# Latest Handoff",
        "",
        f"Status: {status}",
        "",
        summary.strip(),
    ]
    if next_step.strip():
        body.extend(["", "Next:", "", next_step.strip()])
    text = "\n".join(body).rstrip() + "\n"

    latest = root / "handoffs" / "latest.md"
    latest.write_text(text, encoding="utf-8")
    archive = root / "handoffs" / f"{now_iso().replace(':', '').replace('+', 'Z')}.md"
    archive.write_text(text, encoding="utf-8")
    return latest


def run_from_hook() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    if payload.get("stop_hook_active"):
        return 0

    message = payload.get("last_assistant_message") or ""
    if not isinstance(message, str) or not message.strip():
        return 0

    summary = message.strip()
    if len(summary) > MAX_HOOK_SUMMARY_CHARS:
        summary = summary[:MAX_HOOK_SUMMARY_CHARS].rstrip() + "\n...[truncated]"

    if classify_learning(summary) == "RED":
        return 0

    write_handoff(summary=summary, status="stop-hook")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the latest Ralph Codex handoff.")
    parser.add_argument("--summary")
    parser.add_argument("--status", default="unknown")
    parser.add_argument("--next", default="")
    parser.add_argument("--from-hook", action="store_true")
    args = parser.parse_args()

    if args.from_hook:
        return run_from_hook()

    if not args.summary:
        parser.error("--summary is required unless --from-hook is used")

    latest = write_handoff(summary=args.summary, status=args.status, next_step=args.next)
    print(f"HANDOFF_OK {latest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
