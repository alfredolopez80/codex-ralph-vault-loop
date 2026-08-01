#!/usr/bin/env python3
from __future__ import annotations

from shared.paths import read_hook_input
from shared.sol_advisor import has_completion_evidence, is_sol_advisor, mark_advisor


def main() -> int:
    try:
        payload = read_hook_input()
        if is_sol_advisor(payload) and has_completion_evidence(payload):
            mark_advisor(payload, completed=True)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
