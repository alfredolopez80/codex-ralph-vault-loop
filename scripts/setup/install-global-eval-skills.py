#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / ".agents" / "skills"
HELPER_SOURCE = REPO / "scripts" / "autoresearch"
TARGET = Path.home() / ".codex" / "skills"
AGENT_TARGET = Path.home() / ".agents" / "skills"
HELPER_TARGET = Path.home() / ".ralph-codex" / "bin" / "autoresearch"
SKILLS = ("autoresearch", "evaluate", "scorecard")


def path_present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def copy_path(source: Path, target: Path, dry_run: bool, label: str) -> None:
    if dry_run:
        print(f"{source} -> {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if path_present(target):
        backup = target.with_name(f"{target.name}.bak-eval-skill")
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
    print(f"{label} {target}")


def copy_skill(name: str, dry_run: bool) -> None:
    source = SOURCE / name
    copy_path(source, TARGET / name, dry_run, "CODEX_SKILL_INSTALLED")
    copy_path(source, AGENT_TARGET / name, dry_run, "AGENT_SKILL_INSTALLED")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install evaluation skills globally for Codex sessions.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.dry_run:
        TARGET.mkdir(parents=True, exist_ok=True)
        AGENT_TARGET.mkdir(parents=True, exist_ok=True)
    for skill in SKILLS:
        copy_skill(skill, args.dry_run)
    copy_path(HELPER_SOURCE, HELPER_TARGET, args.dry_run, "AUTORESEARCH_HELPERS_INSTALLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
