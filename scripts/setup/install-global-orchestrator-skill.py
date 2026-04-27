#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / ".agents" / "skills" / "orchestrator"
TARGET = Path.home() / ".codex" / "skills" / "orchestrator"


def path_present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def install(dry_run: bool) -> None:
    if dry_run:
        print(f"{SOURCE} -> {TARGET}")
        return
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    if path_present(TARGET):
        backup = TARGET.with_name(f"{TARGET.name}.bak-orchestrator-skill")
        if path_present(backup):
            remove_path(backup)
        if TARGET.is_symlink():
            backup.symlink_to(TARGET.readlink(), target_is_directory=True)
        elif TARGET.is_dir():
            shutil.copytree(TARGET, backup)
        else:
            shutil.copy2(TARGET, backup)
    if path_present(TARGET):
        remove_path(TARGET)
    shutil.copytree(SOURCE, TARGET)
    print(f"SKILL_INSTALLED {TARGET}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the Codex-native orchestrator skill globally.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    install(args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
