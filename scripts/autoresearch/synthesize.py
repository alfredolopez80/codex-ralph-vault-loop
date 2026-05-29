#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import add_common_args, assert_not_red, fail_result, latest_config, print_result, read_ledger, resolve_cwd, session_paths, write_json


def safe_line(value: object, limit: int = 240) -> str:
    text = str(value or "").replace("\n", " ").strip()
    assert_not_red("synthesis", text)
    return text[:limit]


def latest_packet(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    packets = [entry for entry in entries if entry.get("entry_type") == "packet"]
    return packets[-1] if packets else None


def synthesize(args: argparse.Namespace) -> dict[str, Any]:
    cwd = resolve_cwd(args.cwd)
    paths = session_paths(cwd)
    entries = read_ledger(cwd)
    config = latest_config(entries)
    packet = latest_packet(entries)
    if packet is None:
        recommendation = "Run the first scoped packet before synthesizing next hypotheses."
        evidence = "No packet entries exist yet."
    else:
        asi = packet.get("asi") or {}
        recommendation = safe_line(asi.get("next_action_hint") or "Choose the next scoped AutoResearch packet.")
        evidence = safe_line(asi.get("evidence") or packet.get("description") or "Latest packet logged.")

    body = [
        "",
        f"- [ ] {recommendation}",
        f"  - Evidence: {evidence}",
        f"  - Metric: {config.get('metric')} direction={config.get('direction')}",
        f"  - Source segment: {config.get('segment_id')}",
    ]
    assert_not_red("synthesis body", "\n".join(body))
    if not paths["ideas"].exists():
        paths["ideas"].write_text("# AutoResearch Ideas\n", encoding="utf-8")
    with paths["ideas"].open("a", encoding="utf-8") as handle:
        handle.write("\n".join(body) + "\n")

    payload = {
        "ok": True,
        "cwd": str(cwd),
        "segment_id": config.get("segment_id"),
        "recommendation": recommendation,
        "evidence": evidence,
        "ideas_path": str(paths["ideas"]),
    }
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        write_json(output, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthesize local-only AutoResearch next-hypothesis guidance.")
    add_common_args(parser)
    parser.add_argument("--output", default=None, help="Optional JSON recommendation output.")
    args = parser.parse_args()
    try:
        return print_result(synthesize(args))
    except Exception as exc:
        return fail_result(exc)


if __name__ == "__main__":
    raise SystemExit(main())
