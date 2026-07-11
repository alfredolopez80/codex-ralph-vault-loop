#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".codex" / "hooks"))
from shared.local_minikube_grant import digest, root, targets  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("patch_file", type=Path, nargs="?")
    parser.add_argument("--sha256")
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    args = parser.parse_args()
    if args.patch_file:
        patch = args.patch_file.read_text(encoding="utf-8")
        payload_hash = digest(patch)
        patch_targets = targets(patch, args.cwd.resolve())
    else:
        if not args.sha256 or not re.fullmatch(r"[0-9a-f]{64}", args.sha256) or not args.target:
            parser.error("provide patch_file or both --sha256 and --target")
        payload_hash = args.sha256
        synthetic_patch = "\n".join(f"*** Add File: {path}" for path in args.target)
        patch_targets = targets(synthetic_patch, args.cwd.resolve())
    if not patch_targets:
        raise SystemExit("REFUSED: targets must be under .local-notes")
    grant_root = root()
    grant_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(grant_root, 0o700)
    destination = grant_root / f"{payload_hash}.approved"
    destination.write_text("", encoding="utf-8")
    os.chmod(destination, 0o600)
    print(f"APPROVED_ONCE sha256={payload_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
