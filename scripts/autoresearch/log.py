#!/usr/bin/env python3
from __future__ import annotations

import argparse

from common import VALID_STATUSES, add_common_args, append_jsonl, fail_result, fingerprint, is_finite_number, latest_config, parse_asi_arg, print_result, read_json, read_ledger, required_entry_fields, resolve_cwd, session_paths


def log_packet(args: argparse.Namespace) -> dict:
    if args.status not in VALID_STATUSES:
        raise RuntimeError(f"invalid status: {args.status}")
    cwd = resolve_cwd(args.cwd)
    entries = read_ledger(cwd)
    config = latest_config(entries)
    paths = session_paths(cwd)
    if not args.from_last:
        raise RuntimeError("only --from-last is supported so packet evidence remains recoverable")
    last = read_json(paths["last_run"])
    current = fingerprint(cwd, config)
    if last.get("freshness_fingerprint") != current:
        raise RuntimeError("last-run packet is stale; rerun next before logging")
    metric_value = (last.get("metrics") or {}).get(config["metric"])
    if args.status in {"keep", "discard"} and not is_finite_number(metric_value):
        raise RuntimeError("keep/discard requires a finite primary metric")
    asi = parse_asi_arg(args.asi, args.status, args.description)
    entry = {
        **required_entry_fields(config, args.status, last.get("delta"), last.get("hard_gates", {}), asi),
        "entry_type": "packet",
        "description": args.description or "",
        "metrics": last.get("metrics", {}),
        "baseline": last.get("baseline"),
        "last_run_path": str(paths["last_run"]),
    }
    append_jsonl(paths["ledger"], entry)
    return {"ok": True, "cwd": str(cwd), "logged": entry, "continuation": {"shouldContinue": args.status != "crash", "forbidFinalAnswer": False}}


def main() -> int:
    parser = argparse.ArgumentParser(description="Log the latest Ralph AutoResearch packet decision.")
    add_common_args(parser)
    parser.add_argument("--from-last", action="store_true", dest="from_last")
    parser.add_argument("--status", required=True, choices=sorted(VALID_STATUSES))
    parser.add_argument("--description", default="")
    parser.add_argument("--asi", default=None, help="JSON object with hypothesis/evidence/next_action_hint and rollback_reason for rejected packets.")
    args = parser.parse_args()
    try:
        return print_result(log_packet(args))
    except Exception as exc:
        return fail_result(exc)


if __name__ == "__main__":
    raise SystemExit(main())
