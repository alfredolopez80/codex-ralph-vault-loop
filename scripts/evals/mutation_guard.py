#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest_paths(paths: list[Path]) -> dict[str, str]:
    output = {}
    for path in paths:
        if path.exists():
            output[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect unexpected eval harness mutation.")
    parser.add_argument("--baseline")
    parser.add_argument("--write-baseline")
    parser.add_argument("paths", nargs="*", default=["scripts/evals", "config/scorecards", "tests/evals"])
    args = parser.parse_args()

    files = []
    for raw in args.paths:
        path = Path(raw)
        if path.is_dir():
            files.extend(sorted(item for item in path.rglob("*") if item.is_file()))
        else:
            files.append(path)
    current = digest_paths(files)

    if args.write_baseline:
        Path(args.write_baseline).write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"written": args.write_baseline, "files": len(current)}, indent=2, sort_keys=True))
        return 0

    if not args.baseline:
        print(json.dumps({"eval_harness_unchanged": True, "files": len(current)}, indent=2, sort_keys=True))
        return 0

    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    changed = {path: current.get(path) for path, digest in baseline.items() if current.get(path) != digest}
    print(json.dumps({"eval_harness_unchanged": not changed, "changed": changed}, indent=2, sort_keys=True))
    return 1 if changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
