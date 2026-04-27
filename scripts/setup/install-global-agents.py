#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / ".codex" / "agents"
TARGET = Path.home() / ".codex" / "agents"


def main() -> int:
    parser = argparse.ArgumentParser(description="Install repo Codex agents into the global Codex agents directory.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    agents = sorted(path for path in SOURCE.glob("*.toml") if path.is_file())
    if args.dry_run:
        for path in agents:
            print(f"{path} -> {TARGET / path.name}")
        return 0

    TARGET.mkdir(parents=True, exist_ok=True)
    for path in agents:
        target = TARGET / path.name
        if target.exists():
            backup = target.with_suffix(".toml.bak-ralph-agent")
            backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
        shutil.copy2(path, target)
        print(f"AGENT_INSTALLED {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
