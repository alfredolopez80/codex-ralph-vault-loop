#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".codex" / "hooks"))

from shared.local_minikube_grant import create_patch_marker, patch_grant_from_request  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Approve one exact static patch for one retry.")
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--cwd", required=True, type=Path)
    parser.add_argument("--target", required=True, action="append")
    args = parser.parse_args()

    grant = patch_grant_from_request(args.sha256, args.cwd.resolve(), args.target)
    if grant is None:
        raise SystemExit("REFUSED: invalid patch hash, cwd, or in-repository targets")
    create_patch_marker(grant)
    print(f"APPROVED_ONCE sha256={grant.patch_sha256} targets={','.join(grant.targets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
