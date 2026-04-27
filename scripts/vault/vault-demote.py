#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from _vault_common import default_project, sanitize_slug, vault_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Move a vault note out of curated areas into project raw.")
    parser.add_argument("path")
    parser.add_argument("--project", default=default_project())
    args = parser.parse_args()

    source = Path(args.path).expanduser()
    if not source.is_absolute():
        source = vault_dir() / source
    if not source.exists():
        raise SystemExit(f"missing note: {source}")

    destination_dir = vault_dir() / "projects" / sanitize_slug(args.project) / "raw"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source.name
    if source.resolve() == destination.resolve():
        print(f"VAULT_DEMOTE_NOOP {destination}")
        return 0
    shutil.move(str(source), str(destination))
    print(f"VAULT_DEMOTE_OK {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
