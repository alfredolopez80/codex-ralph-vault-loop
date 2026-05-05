#!/usr/bin/env python3
from __future__ import annotations

import argparse

from shared.file_line_candidates import scan_paths, workspace_root
from shared.file_line_policy import emit_block, line_limit, oversized
from shared.paths import read_hook_input


def main() -> int:
    parser = argparse.ArgumentParser(description="Block Codex-created god files.")
    parser.add_argument("--event", choices=["PostToolUse", "Stop"], default="PostToolUse")
    args = parser.parse_args()

    payload = read_hook_input()
    root = workspace_root(payload)
    limit = line_limit()
    findings = oversized(scan_paths(payload, args.event), root, limit)
    if findings:
        emit_block(findings, limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
