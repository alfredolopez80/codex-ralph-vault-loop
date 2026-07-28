#!/usr/bin/env python3
from __future__ import annotations

import json

from _gate_common import detect_project


def main() -> int:
    print(json.dumps(detect_project(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
