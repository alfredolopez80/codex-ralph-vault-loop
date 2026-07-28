#!/usr/bin/env python3
from __future__ import annotations

import argparse

from _vault_common import iter_markdown_files, vault_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Search local vault Markdown notes.")
    parser.add_argument("query")
    parser.add_argument("--case-sensitive", action="store_true")
    args = parser.parse_args()

    needle = args.query if args.case_sensitive else args.query.lower()
    matches = 0
    for path in iter_markdown_files(vault_dir()):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            haystack = line if args.case_sensitive else line.lower()
            if needle in haystack:
                print(f"{path}:{line_number}:{line}")
                matches += 1
    return 0 if matches else 1


if __name__ == "__main__":
    raise SystemExit(main())
