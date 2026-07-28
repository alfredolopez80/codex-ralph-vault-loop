#!/usr/bin/env python3
from __future__ import annotations

import argparse

from _vault_common import (
    content_hash,
    classify_note,
    default_agent,
    default_project,
    init_vault,
    note_path,
    render_note,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Save a GREEN or YELLOW note to the local vault.")
    parser.add_argument("--classification", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--project", default=default_project())
    parser.add_argument("--agent", default=default_agent())
    parser.add_argument("--source", default="manual")
    parser.add_argument("--title")
    args = parser.parse_args()

    classification, findings, safe_text = classify_note(args.text, args.classification)

    if classification == "RED":
        labels = ",".join(finding["label"] for finding in findings) if findings else "requested-red"
        print(f"VAULT_SAVE_SKIPPED_RED findings={labels}")
        return 0

    init_vault(args.project, args.agent)
    digest = content_hash(safe_text)
    path = note_path(classification, digest, args.project)
    if path.exists():
        print(f"VAULT_SAVE_DEDUP {path}")
        return 0

    path.write_text(
        render_note(
            text=safe_text,
            classification=classification,
            project=args.project,
            agent=args.agent,
            source=args.source,
            title=args.title,
        ),
        encoding="utf-8",
    )
    print(f"VAULT_SAVE_OK {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
