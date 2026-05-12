#!/usr/bin/env python3
from __future__ import annotations

from shared.paths import REPO_ROOT, ensure_runtime, read_hook_input

import subprocess
import sys


def main() -> int:
    read_hook_input()
    ensure_runtime()
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
                REPO_ROOT.name,
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
    wakeup = REPO_ROOT / "scripts" / "memory" / "wakeup.py"
    if not wakeup.exists():
        return 0
    result = subprocess.run([sys.executable, str(wakeup)], text=True, capture_output=True, check=False, timeout=20)
    if result.stdout.strip():
        print(result.stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
