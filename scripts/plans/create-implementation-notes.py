#!/usr/bin/env python3
"""Compatibility adapter for the historical create-notes entrypoint.

New plan starts delegate to ``progress.py start``. The old HTML/index behavior
is reachable only through legacy-only flags or ``--compat-legacy``.
"""

from __future__ import annotations

import sys

from legacy_compat import create


def _legacy_mode(argv: list[str]) -> bool:
    return "--compat-legacy" in argv or any(
        flag in argv for flag in ("--notes", "--approved", "--allow-docs", "--force", "--active-root", "--primary-root")
    )


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    if not _legacy_mode(raw):
        from progress import main as progress_main

        return progress_main(["start", *raw])
    return create([item for item in raw if item != "--compat-legacy"])


if __name__ == "__main__":
    raise SystemExit(main())
