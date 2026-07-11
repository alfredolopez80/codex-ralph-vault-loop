#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".codex" / "hooks"))
from shared.local_minikube_grant import root  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Approve one exact risky command for one retry.")
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{64}", args.sha256):
        parser.error("invalid SHA-256")
    marker_root = root()
    marker_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(marker_root, 0o700)
    marker = marker_root / f"command-{args.sha256}.approved"
    marker.write_text("", encoding="utf-8")
    os.chmod(marker, 0o600)
    print(f"APPROVED_ONCE sha256={args.sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
