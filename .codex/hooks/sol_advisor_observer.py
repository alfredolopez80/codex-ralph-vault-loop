#!/usr/bin/env python3
from __future__ import annotations

from shared.paths import read_hook_input
from shared.sol_advisor import observe_failure


def run(payload: dict) -> None:
    observe_failure(payload)


def main() -> int:
    try:
        run(read_hook_input())
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
