#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from common import VALID_STATUSES, add_common_args, append_jsonl, assert_keep_allowed, fail_result, fingerprint, is_finite_number, latest_config, parse_asi_arg, print_result, read_json, read_ledger, required_entry_fields, resolve_cwd, session_paths
from generation import atomic_write_json


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
    hard_gates = last.get("hard_gates", {})
    if args.status == "keep":
        assert_keep_allowed(hard_gates)
    asi = parse_asi_arg(args.asi, args.status, args.description)
    entry = {
        **required_entry_fields(config, args.status, last.get("delta"), hard_gates, asi),
        "entry_type": "packet",
        "description": args.description or "",
        "metrics": last.get("metrics", {}),
        "baseline": last.get("baseline"),
        "baseline_policy": last.get("baseline_policy"),
        "last_run_path": str(paths["last_run"]),
    }
    append_jsonl(paths["ledger"], entry)
    generation = last.get("generation") or {}
    decision_file = ((generation.get("files") or {}).get("decision")) if isinstance(generation, dict) else None
    if decision_file:
        decision_path = Path(decision_file).resolve()
        try:
            decision_path.relative_to(cwd.resolve())
        except ValueError as exc:
            raise RuntimeError("generation decision path escapes AutoResearch cwd") from exc
        atomic_write_json(
            decision_path,
            {
                "status": args.status,
                "delta": last.get("delta"),
                "baseline": last.get("baseline"),
                "baseline_policy": last.get("baseline_policy"),
                "logged_at": entry["created_at"],
            },
        )
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
