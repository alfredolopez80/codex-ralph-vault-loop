#!/usr/bin/env python3
from __future__ import annotations

import argparse

from _vault_common import iter_markdown_files, parse_frontmatter, vault_dir


REQUIRED_FRONTMATTER = {"title", "classification", "scope", "hash", "created_at"}
RED_MARKERS = ("api_key", "private key", "secret=", "password=", "token=")


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint local vault notes for basic metadata and RED markers.")
    parser.parse_args()

    issues = []
    for path in iter_markdown_files(vault_dir()):
        text = path.read_text(encoding="utf-8")
        metadata = parse_frontmatter(text)
        missing = sorted(REQUIRED_FRONTMATTER - set(metadata))
        if missing:
            issues.append(f"{path}: missing frontmatter keys: {', '.join(missing)}")
        lowered = text.lower()
        for marker in RED_MARKERS:
            if marker in lowered:
                issues.append(f"{path}: possible RED marker: {marker}")

    if issues:
        print("\n".join(issues))
        return 1
    print("VAULT_LINT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
