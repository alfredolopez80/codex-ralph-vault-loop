#!/usr/bin/env python3
from __future__ import annotations

import argparse

from shared.file_line_candidates import scan_paths, workspace_root
from shared.file_line_policy import block_payload, line_limit, oversized
from shared.paths import read_hook_input, write_json


def evaluate(payload: dict, event: str = "PostToolUse") -> dict | None:
    root = workspace_root(payload)
    findings = oversized(scan_paths(payload, event), root, line_limit())
    return block_payload(findings, line_limit()) if findings else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Block Codex-created god files.")
    parser.add_argument("--event", choices=["PostToolUse", "Stop"], default="PostToolUse")
    args = parser.parse_args()

    payload = read_hook_input()
    response = evaluate(payload, args.event)
    if response:
        write_json(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
