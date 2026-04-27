#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / ".agents" / "skills"
TARGET = Path.home() / ".codex" / "skills"
SKILLS = ("cost-router", "model-router")


def copy_skill(name: str, dry_run: bool) -> None:
    source = SOURCE / name
    target = TARGET / name
    if dry_run:
        print(f"{source} -> {target}")
        return
    if target.exists():
        backup = target.with_name(f"{target.name}.bak-router-skill")
        if backup.exists():
            shutil.rmtree(backup)
        shutil.copytree(target, backup)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    print(f"SKILL_INSTALLED {target}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install router skills globally for Codex sessions.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    TARGET.mkdir(parents=True, exist_ok=True)
    for skill in SKILLS:
        copy_skill(skill, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
