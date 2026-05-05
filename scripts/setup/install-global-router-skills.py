#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
HOOK_INSTALLER = REPO / "scripts" / "setup" / "install-global-hooks.py"
SOURCE = REPO / ".agents" / "skills"
AGENT_SOURCE = REPO / ".codex" / "agents"
SKILL_TARGET = Path.home() / ".codex" / "skills"
AGENT_TARGET = Path.home() / ".codex" / "agents"
HOOKS_TARGET = Path.home() / ".codex" / "hooks.json"
BACKUP_ROOT = Path.home() / ".ralph-codex" / "backups" / "router-install"
SKILLS = ("cost-router", "model-router")


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def hook_config() -> dict:
    spec = importlib.util.spec_from_file_location("install_global_hooks", HOOK_INSTALLER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load hook installer: {HOOK_INSTALLER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.hook_config()


def backup(target: Path, stamp: str) -> None:
    if not target.exists() and not target.is_symlink():
        return
    destination = BACKUP_ROOT / stamp / target.relative_to(Path.home())
    destination.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        destination.symlink_to(target.readlink())
    elif target.is_dir():
        shutil.copytree(target, destination)
    else:
        shutil.copy2(target, destination)
    print(f"ROUTER_INSTALL_BACKUP {target} -> {destination}")


def copy_path(source: Path, target: Path, dry_run: bool, stamp: str) -> None:
    if dry_run:
        print(f"{source} -> {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    backup(target, stamp)
    if target.exists() or target.is_symlink():
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)
    print(f"ROUTER_INSTALL_OK {target}")


def copy_skill(name: str, dry_run: bool, stamp: str) -> None:
    copy_path(SOURCE / name, SKILL_TARGET / name, dry_run, stamp)


def copy_agents(dry_run: bool, stamp: str) -> None:
    for source in sorted(AGENT_SOURCE.glob("*.toml")):
        copy_path(source, AGENT_TARGET / source.name, dry_run, stamp)


def write_hooks(dry_run: bool, stamp: str) -> None:
    data = hook_config()
    if dry_run:
        print(f"{REPO / '.codex' / 'hooks'} -> {HOOKS_TARGET}")
        print(json.dumps(data, indent=2))
        return
    HOOKS_TARGET.parent.mkdir(parents=True, exist_ok=True)
    backup(HOOKS_TARGET, stamp)
    HOOKS_TARGET.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"ROUTER_INSTALL_OK {HOOKS_TARGET}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install router skills, Ralph agents, and hooks globally for Codex sessions.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skills-only", action="store_true", help="Install only cost-router and model-router skills.")
    parser.add_argument("--no-hooks", action="store_true", help="Skip global hooks.json installation.")
    parser.add_argument("--no-agents", action="store_true", help="Skip global Ralph subagent installation.")
    args = parser.parse_args()

    stamp = timestamp()
    for skill in SKILLS:
        copy_skill(skill, args.dry_run, stamp)
    if not args.skills_only and not args.no_agents:
        copy_agents(args.dry_run, stamp)
    if not args.skills_only and not args.no_hooks:
        write_hooks(args.dry_run, stamp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
