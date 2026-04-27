#!/usr/bin/env python3
from __future__ import annotations

from shared.paths import REPO_ROOT, ensure_runtime, read_hook_input

import subprocess
import sys


def main() -> int:
    read_hook_input()
    ensure_runtime()
    wakeup = REPO_ROOT / "scripts" / "memory" / "wakeup.py"
    if not wakeup.exists():
        return 0
    result = subprocess.run([sys.executable, str(wakeup)], text=True, capture_output=True, check=False, timeout=20)
    if result.stdout.strip():
        print(result.stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
