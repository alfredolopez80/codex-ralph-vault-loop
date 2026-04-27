#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys

from _cost_common import estimate_context, redact_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Redact text before external MCP routing.")
    parser.add_argument("--text")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    text = args.text if args.text is not None else sys.stdin.read()
    redacted, changed = redact_text(text)
    if args.json:
        payload = {"redacted": redacted, "changed": changed, "context": estimate_context(redacted)}
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(redacted, end="" if redacted.endswith("\n") else "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
