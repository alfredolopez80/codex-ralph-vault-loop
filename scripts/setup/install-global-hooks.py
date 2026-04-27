#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
GLOBAL_HOOKS = Path.home() / ".codex" / "hooks.json"


def hook_config() -> dict:
    wakeup = REPO / "scripts" / "memory" / "wakeup.py"
    slop = REPO / "scripts" / "gates" / "codex_stop_slop_guard.py"
    handoff = REPO / "scripts" / "memory" / "handoff.py"
    return {
        "version": 1,
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"python3 {wakeup}",
                            "timeout": 20,
                        }
                    ]
                }
            ],
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"python3 {slop}",
                            "timeout": 45,
                        },
                        {
                            "type": "command",
                            "command": f"python3 {handoff} --from-hook",
                            "timeout": 20,
                        },
                    ]
                }
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Install global Codex hooks for Ralph memory.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    data = hook_config()
    if args.dry_run:
        print(json.dumps(data, indent=2))
        return 0

    GLOBAL_HOOKS.parent.mkdir(parents=True, exist_ok=True)
    if GLOBAL_HOOKS.exists():
        backup = GLOBAL_HOOKS.with_suffix(".json.bak-global-hooks")
        backup.write_text(GLOBAL_HOOKS.read_text(encoding="utf-8"), encoding="utf-8")
    GLOBAL_HOOKS.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"GLOBAL_HOOKS_OK {GLOBAL_HOOKS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
