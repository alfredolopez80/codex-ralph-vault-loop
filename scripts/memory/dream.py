#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from _dream_core import build_report
from _dream_outputs import write_dream_state, write_reports, write_vault_inbox
from _memory_common import ensure_runtime, now_iso
from _promotion import summarize_promotions


def apply_candidates() -> int:
    print("DREAM_APPLY_UNIMPLEMENTED use --dry-run or --emit-patch for reviewable candidates")
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Consolidate Ralph memory handoffs and ledgers into reviewable candidates.")
    parser.add_argument("--dry-run", action="store_true", help="Generate reports without mutating canonical layers. This is the default.")
    parser.add_argument("--since-days", type=int)
    parser.add_argument("--max-items", type=int, default=50)
    parser.add_argument("--emit-patch", action="store_true", help="Emit a reviewable Markdown layer patch proposal.")
    parser.add_argument("--auto-update-state", action="store_true", help="Update L4 dream state for future wakeup context.")
    parser.add_argument("--vault-inbox", action="store_true", help="Write a reviewable dream digest into the MiVault project inbox.")
    parser.add_argument("--vault-project", default=Path.cwd().name, help="Project slug for --vault-inbox.")
    parser.add_argument("--assist-promote", action="store_true", help="Auto-promote very safe candidates and queue ambiguous candidates for review.")
    parser.add_argument("--apply-candidates", action="store_true", help="Reserved for an approved future apply flow.")
    args = parser.parse_args()

    if args.apply_candidates:
        return apply_candidates()

    root = ensure_runtime()
    report = build_report(root, args.since_days, args.max_items, now_iso())
    md_path, _json_path = write_reports(root, report, args.emit_patch)
    if args.assist_promote:
        promotion = summarize_promotions(root, report)
        print(
            "DREAM_PROMOTION_OK "
            f"auto={len(promotion['auto_promoted'])} "
            f"review={len(promotion['review_requested'])}"
        )
    if args.auto_update_state:
        state_md, _state_json = write_dream_state(root, report)
        print(f"DREAM_STATE_OK {state_md}")
    if args.vault_inbox:
        inbox_path = write_vault_inbox(report, args.vault_project)
        print(f"DREAM_VAULT_INBOX_OK {inbox_path}")
    print(f"DREAM_OK {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
