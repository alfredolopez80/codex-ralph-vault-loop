#!/usr/bin/env python3
from __future__ import annotations

import os

from shared.active_context import active_context_from_payload
from shared.paths import REPO_ROOT, ensure_runtime, read_hook_input

import subprocess
import sys


def main() -> int:
    payload = read_hook_input()
    context = active_context_from_payload(payload)
    ensure_runtime()
    env = {
        **os.environ.copy(),
        "VAULT_PROJECT": context.project_slug,
        "RALPH_PROJECT_ID": context.project_id,
        "RALPH_WORKSPACE_ROOT": str(context.workspace_root),
        "RALPH_SESSION_ID": context.session_id,
    }
    scheduler = REPO_ROOT / "scripts" / "memory" / "dream-scheduler.py"
    if scheduler.exists():
        subprocess.run(
            [
                sys.executable,
                str(scheduler),
                "--catch-up",
                "--target-time",
                "11:30",
                "--max-seconds",
                "15",
                "--vault-project",
                context.project_slug,
                "--project-id",
                context.project_id,
                "--workspace-root",
                str(context.workspace_root),
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
            env=env,
        )
    wakeup = REPO_ROOT / "scripts" / "memory" / "wakeup.py"
    if not wakeup.exists():
        print(f"RALPH_WAKEUP_STATUS=missing path={wakeup}")
        return 0
    result = subprocess.run(
        [
            sys.executable,
            str(wakeup),
            "--project",
            context.project_slug,
            "--project-id",
            context.project_id,
            "--workspace-root",
            str(context.workspace_root),
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
        env=env,
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
