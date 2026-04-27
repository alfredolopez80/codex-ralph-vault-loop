#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _eval_common import detect_eval_gaming_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect obvious eval-gaming language in files.")
    parser.add_argument("paths", nargs="*", default=["."])
    args = parser.parse_args()

    findings = []
    for raw in args.paths:
        path = Path(raw)
        files = sorted(item for item in path.rglob("*") if item.is_file()) if path.is_dir() else [path]
        for file in files:
            if ".git" in file.parts or file.suffix in {".pyc", ".png", ".jpg", ".jpeg"}:
                continue
            try:
                text = file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            markers = detect_eval_gaming_text(text)
            if markers:
                findings.append({"path": str(file), "markers": markers})
    print(json.dumps({"no_eval_gaming": not findings, "findings": findings}, indent=2, sort_keys=True))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
