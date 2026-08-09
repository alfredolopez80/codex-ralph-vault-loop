#!/usr/bin/env python3
"""Compatibility adapter for legacy HTML note append behavior.

New progress writes belong to ``progress.py record``. This script remains only
for explicit legacy option calls and reader-first compatibility evidence.
"""

from __future__ import annotations

import sys

from legacy_compat import append


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    # The --notes/--category/--decision surface is itself the explicit legacy
    # contract; --compat-legacy makes that intent visible for new callers.
    return append([item for item in raw if item != "--compat-legacy"])


if __name__ == "__main__":
    raise SystemExit(main())
