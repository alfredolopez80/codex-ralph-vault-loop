#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from _vault_common import iter_markdown_files, parse_frontmatter, vault_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a JSON index for local vault notes.")
    parser.add_argument("--output", default="_index.json")
    args = parser.parse_args()

    root = vault_dir()
    notes = []
    for path in iter_markdown_files(root):
        text = path.read_text(encoding="utf-8")
        notes.append(
            {
                "path": str(path.relative_to(root)),
                "metadata": parse_frontmatter(text),
                "bytes": path.stat().st_size,
            }
        )

    output = root / args.output
    output.write_text(json.dumps({"notes": notes}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"VAULT_INDEX_OK {output} {len(notes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
