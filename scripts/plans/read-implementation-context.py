#!/usr/bin/env python3
"""Compatibility adapter for legacy HTML implementation context reads."""

from __future__ import annotations

import sys

from legacy_compat import read_context


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    return read_context([item for item in raw if item != "--compat-legacy"])


if __name__ == "__main__":
    raise SystemExit(main())
