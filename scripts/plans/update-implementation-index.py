#!/usr/bin/env python3
"""Compatibility adapter for the historical schema-v2 implementation index."""

from __future__ import annotations

import sys

from legacy_compat import update_index


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    return update_index([item for item in raw if item != "--compat-legacy"])


if __name__ == "__main__":
    raise SystemExit(main())
