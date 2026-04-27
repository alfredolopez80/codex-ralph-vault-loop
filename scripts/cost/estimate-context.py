#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys

from _cost_common import estimate_context


def main() -> int:
    parser = argparse.ArgumentParser(description="Estimate chars, words, and rough tokens for context.")
    parser.add_argument("--text")
    args = parser.parse_args()

    text = args.text if args.text is not None else sys.stdin.read()
    print(json.dumps(estimate_context(text), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
