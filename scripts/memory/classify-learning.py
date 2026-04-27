#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from classify_learning import classify_learning


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify a learning as GREEN, YELLOW, or RED.")
    parser.add_argument("--text", required=True)
    parser.add_argument("--classification")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    classification = classify_learning(args.text, args.classification)
    if args.json:
        print(json.dumps({"classification": classification}, sort_keys=True))
    else:
        print(classification)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
