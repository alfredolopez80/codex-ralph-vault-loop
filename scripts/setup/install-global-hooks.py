#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shlex
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GLOBAL_HOOKS = Path.home() / ".codex" / "hooks.json"
GLOBAL_HOOK_DIR = Path.home() / ".codex" / "hooks"
GLOBAL_SKILL_ROOTS = (Path.home() / ".agents" / "skills", Path.home() / ".codex" / "skills")
MANAGED_SKILL_SOURCE_ROOTS = (REPO / ".agents" / "skills", REPO / "plugins")
GLOBAL_AGENT_ROOT = Path.home() / ".codex" / "agents"
MANAGED_AGENT_SOURCE_ROOT = REPO / ".codex" / "agents"


def q(path: Path) -> str:
    return shlex.quote(str(path))


HOOK_ROLES: dict[str, tuple[tuple[str, int], ...]] = {
    "SessionStart": (("session_start_wakeup", 45),),
    "UserPromptSubmit": (
        ("universal_prompt_classifier", 10),
        ("user_prompt_capture", 10),
        ("user_prompt_improve", 10),
        ("continuity_prompt_context", 10),
    ),
    "PreToolUse": (("pre_tool_guard", 10),),
    "PostToolUse": (
        ("file_line_guard_post_tool", 10),
        ("shaping_ripple", 10),
        ("post_tool_extract_memory", 10),
        ("post_tool_checkpoint", 10),
        ("post_tool_cost_ledger", 10),
    ),
    "Stop": (
        ("anti_rationalization_stop", 10),
        ("ralph_stop_quality_gate", 10),
        ("file_line_guard_stop", 20),
        ("stop_route_decision_warn", 10),
        ("implementation_notes_guard", 10),
        ("stop_persist_memory", 20),
        ("stop_memory_promotion_review", 20),
    ),
}


def dispatch_command(event: str, role: str) -> str:
    dispatcher = q(GLOBAL_HOOK_DIR / "global_hook_dispatch.py")
    return f"python3 {dispatcher} --event {shlex.quote(event)} --role {shlex.quote(role)}"


def hook_config() -> dict:
    return {
        "hooks": {
            event: [{"hooks": [{"type": "command", "command": dispatch_command(event, role), "timeout": timeout} for role, timeout in roles]}]
            for event, roles in HOOK_ROLES.items()
        }
    }


def is_codex_worktree(path: Path) -> bool:
    try:
        resolved = path.resolve()
        codex_worktrees = (Path.home() / ".codex" / "worktrees").resolve()
        resolved.relative_to(codex_worktrees)
        return True
    except ValueError:
        return False


def validate_source_repo(allow_worktree_source: bool) -> None:
    if is_codex_worktree(REPO) and not allow_worktree_source:
        raise SystemExit(
            "GLOBAL_HOOKS_REFUSED_WORKTREE_SOURCE "
            f"repo={REPO} stable_repo_hint=primary checkout outside ~/.codex/worktrees"
        )


def validate_managed_links_match_source() -> None:
    for global_root in GLOBAL_SKILL_ROOTS:
        for source_root in MANAGED_SKILL_SOURCE_ROOTS:
            if not source_root.is_dir():
                continue
            for source in source_root.iterdir():
                target = global_root / source.name
                if target.is_symlink() and target.resolve() != source.resolve():
                    raise SystemExit(
                        "GLOBAL_HOOKS_REFUSED_SKILL_SOURCE_MISMATCH "
                        f"target={target} expected={source} actual={target.resolve()}"
                    )

    if not MANAGED_AGENT_SOURCE_ROOT.is_dir():
        return
    for source in MANAGED_AGENT_SOURCE_ROOT.iterdir():
        target = GLOBAL_AGENT_ROOT / source.name
        if target.is_symlink() and target.resolve() != source.resolve():
            raise SystemExit(
                "GLOBAL_HOOKS_REFUSED_AGENT_SOURCE_MISMATCH "
                f"target={target} expected={source} actual={target.resolve()}"
            )


def validate_global_source(migrate_global_source: bool) -> None:
    marker = GLOBAL_HOOK_DIR / ".ralph-repo-root"
    if not marker.exists():
        return
    if marker.is_symlink() or not marker.is_file():
        raise SystemExit(f"GLOBAL_HOOKS_REFUSED_INVALID_SOURCE_MARKER marker={marker}")
    installed_root = marker.read_text(encoding="utf-8").strip()
    if not installed_root:
        raise SystemExit(f"GLOBAL_HOOKS_REFUSED_EMPTY_SOURCE_MARKER marker={marker}")
    if installed_root != str(REPO):
        if not migrate_global_source:
            raise SystemExit(
                "GLOBAL_HOOKS_REFUSED_SOURCE_MISMATCH "
                f"marker={marker} hint=run the full global installer migration"
            )
        validate_managed_links_match_source()


def reject_symlink_target(path: Path, label: str) -> None:
    if path.is_symlink():
        raise SystemExit(f"GLOBAL_HOOKS_REFUSED_SYMLINK_TARGET {label}={path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install global Codex hooks for Ralph memory.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-worktree-source", action="store_true", help="Development-only override for installing from a Codex worktree.")
    parser.add_argument("--verify-migration", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--complete-migration", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.verify_migration and args.complete_migration:
        raise SystemExit("GLOBAL_HOOKS_REFUSED_INVALID_MIGRATION_PHASE")
    validate_source_repo(args.allow_worktree_source)
    migration_requested = args.verify_migration or args.complete_migration
    validate_global_source(migration_requested)
    reject_symlink_target(GLOBAL_HOOKS, "hooks_json")
    reject_symlink_target(GLOBAL_HOOK_DIR, "hooks_dir")

    if args.verify_migration:
        print(f"GLOBAL_HOOKS_MIGRATION_PREFLIGHT_PASS repo={REPO}")
        return 0

    data = hook_config()
    if args.dry_run:
        print(f"GLOBAL_HOOKS_DRY_RUN copy {REPO / '.codex' / 'hooks'} -> {GLOBAL_HOOK_DIR}")
        print(f"GLOBAL_HOOKS_DRY_RUN write {GLOBAL_HOOK_DIR / '.ralph-repo-root'}")
        print(f"GLOBAL_HOOKS_DRY_RUN write {GLOBAL_HOOKS}")
        print(json.dumps(data, indent=2))
        return 0

    GLOBAL_HOOKS.parent.mkdir(parents=True, exist_ok=True)
    if GLOBAL_HOOK_DIR.exists():
        backup_dir = GLOBAL_HOOK_DIR.with_name("hooks.bak-global-hooks")
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        shutil.copytree(GLOBAL_HOOK_DIR, backup_dir, symlinks=True)

    if GLOBAL_HOOK_DIR.exists():
        shutil.rmtree(GLOBAL_HOOK_DIR)
    shutil.copytree(REPO / ".codex" / "hooks", GLOBAL_HOOK_DIR, symlinks=True)
    (GLOBAL_HOOK_DIR / ".ralph-repo-root").write_text(str(REPO) + "\n", encoding="utf-8")

    if GLOBAL_HOOKS.exists():
        backup = GLOBAL_HOOKS.with_suffix(".json.bak-global-hooks")
        backup.write_text(GLOBAL_HOOKS.read_text(encoding="utf-8"), encoding="utf-8")
    GLOBAL_HOOKS.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"GLOBAL_HOOKS_OK {GLOBAL_HOOKS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
