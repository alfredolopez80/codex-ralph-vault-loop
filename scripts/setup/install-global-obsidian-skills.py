#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / ".agents" / "skills"
TARGET = Path.home() / ".codex" / "skills"
SKILLS = ("obsidian-capture", "obsidian-spec")


def path_present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def copy_skill(name: str, dry_run: bool) -> None:
    source = SOURCE / name
    target = TARGET / name
    if dry_run:
        print(f"{source} -> {target}")
        return
    if path_present(target):
        backup = target.with_name(f"{target.name}.bak-obsidian-skill")
        if path_present(backup):
            remove_path(backup)
        if target.is_symlink():
            backup.symlink_to(target.readlink(), target_is_directory=True)
        elif target.is_dir():
            shutil.copytree(target, backup)
        else:
            shutil.copy2(target, backup)
    if path_present(target):
        remove_path(target)
    shutil.copytree(source, target)
    print(f"SKILL_INSTALLED {target}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Obsidian vault skills globally for Codex sessions.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.dry_run:
        TARGET.mkdir(parents=True, exist_ok=True)
    for skill in SKILLS:
        copy_skill(skill, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
