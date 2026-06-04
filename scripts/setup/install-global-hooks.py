#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import shlex
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
GLOBAL_HOOKS = Path.home() / ".codex" / "hooks.json"
GLOBAL_HOOK_DIR = Path.home() / ".codex" / "hooks"
GLOBAL_SLOP_GUARD = GLOBAL_HOOK_DIR / "codex_stop_slop_guard.py"


def q(path: Path) -> str:
    return shlex.quote(str(path))


def hook_config() -> dict:
    hooks = GLOBAL_HOOK_DIR
    slop = GLOBAL_SLOP_GUARD
    return {
        "version": 1,
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"python3 {q(hooks / 'session_start_wakeup.py')}",
                            "timeout": 45,
                        }
                    ]
                }
            ],
            "UserPromptSubmit": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"bash {q(hooks / 'universal-prompt-classifier.sh')}",
                            "timeout": 10,
                        },
                        {
                            "type": "command",
                            "command": f"bash {q(hooks / 'aristotle-analysis-display.sh')}",
                            "timeout": 10,
                        },
                        {
                            "type": "command",
                            "command": f"python3 {q(hooks / 'user_prompt_capture.py')}",
                            "timeout": 10,
                        },
                        {
                            "type": "command",
                            "command": f"python3 {q(hooks / 'continuity_prompt_context.py')}",
                            "timeout": 10,
                        }
                    ]
                }
            ],
            "PreToolUse": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"python3 {q(hooks / 'pre_tool_guard.py')}",
                            "timeout": 10,
                        }
                    ]
                }
            ],
            "PostToolUse": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"python3 {q(hooks / 'file_line_guard.py')} --event PostToolUse",
                            "timeout": 10,
                        },
                        {
                            "type": "command",
                            "command": f"python3 {q(hooks / 'shaping_ripple.py')}",
                            "timeout": 10,
                        },
                        {
                            "type": "command",
                            "command": f"python3 {q(hooks / 'post_tool_extract_memory.py')}",
                            "timeout": 10,
                        },
                        {
                            "type": "command",
                            "command": f"python3 {q(hooks / 'post_tool_checkpoint.py')}",
                            "timeout": 10,
                        },
                        {
                            "type": "command",
                            "command": f"python3 {q(hooks / 'post_tool_cost_ledger.py')}",
                            "timeout": 10,
                        },
                    ]
                }
            ],
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"bash {q(hooks / 'anti-rationalization-stop.sh')}",
                            "timeout": 10,
                        },
                        {
                            "type": "command",
                            "command": f"bash {q(hooks / 'ralph-stop-quality-gate.sh')}",
                            "timeout": 10,
                        },
                        {
                            "type": "command",
                            "command": f"python3 {q(hooks / 'file_line_guard.py')} --event Stop",
                            "timeout": 20,
                        },
                        {
                            "type": "command",
                            "command": f"python3 {q(slop)}",
                            "timeout": 45,
                        },
                        {
                            "type": "command",
                            "command": f"python3 {q(hooks / 'stop_route_decision_warn.py')}",
                            "timeout": 10,
                        },
                        {
                            "type": "command",
                            "command": f"python3 {q(hooks / 'implementation_notes_guard.py')}",
                            "timeout": 10,
                        },
                        {
                            "type": "command",
                            "command": f"python3 {q(hooks / 'stop_persist_memory.py')}",
                            "timeout": 20,
                        },
                        {
                            "type": "command",
                            "command": f"python3 {q(hooks / 'stop_memory_promotion_review.py')}",
                            "timeout": 20,
                        },
                    ]
                }
            ],
        },
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


def reject_symlink_target(path: Path, label: str) -> None:
    if path.is_symlink():
        raise SystemExit(f"GLOBAL_HOOKS_REFUSED_SYMLINK_TARGET {label}={path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install global Codex hooks for Ralph memory.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-worktree-source", action="store_true", help="Development-only override for installing from a Codex worktree.")
    args = parser.parse_args()
    validate_source_repo(args.allow_worktree_source)
    reject_symlink_target(GLOBAL_HOOKS, "hooks_json")
    reject_symlink_target(GLOBAL_HOOK_DIR, "hooks_dir")

    data = hook_config()
    if args.dry_run:
        print(f"GLOBAL_HOOKS_DRY_RUN copy {REPO / '.codex' / 'hooks'} -> {GLOBAL_HOOK_DIR}")
        print(f"GLOBAL_HOOKS_DRY_RUN write {GLOBAL_HOOK_DIR / '.ralph-repo-root'}")
        print(f"GLOBAL_HOOKS_DRY_RUN copy {REPO / 'scripts' / 'gates' / 'codex_stop_slop_guard.py'} -> {GLOBAL_SLOP_GUARD}")
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
    shutil.copy2(REPO / "scripts" / "gates" / "codex_stop_slop_guard.py", GLOBAL_SLOP_GUARD)

    if GLOBAL_HOOKS.exists():
        backup = GLOBAL_HOOKS.with_suffix(".json.bak-global-hooks")
        backup.write_text(GLOBAL_HOOKS.read_text(encoding="utf-8"), encoding="utf-8")
    GLOBAL_HOOKS.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"GLOBAL_HOOKS_OK {GLOBAL_HOOKS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
