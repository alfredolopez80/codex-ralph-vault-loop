#!/usr/bin/env python3
from __future__ import annotations

import argparse

from common import add_common_args, detect_upstream_backend, fail_result, latest_config, print_result, read_ledger, resolve_cwd, session_paths


def summarize(cwd_raw: str | None, compact: bool) -> dict:
    cwd = resolve_cwd(cwd_raw)
    entries = read_ledger(cwd)
    config = latest_config(entries)
    packets = [entry for entry in entries if entry.get("entry_type") == "packet"]
    kept = [entry for entry in packets if entry.get("status") == "keep"]
    discarded = [entry for entry in packets if entry.get("status") == "discard"]
    latest = packets[-1] if packets else None
    payload = {
        "ok": True,
        "cwd": str(cwd),
        "segment_id": config["segment_id"],
        "scorecard": {"id": config["scorecard_id"], "version": config["scorecard_version"]},
        "metric": config["metric"],
        "direction": config["direction"],
        "runs": len(packets),
        "kept": len(kept),
        "discarded": len(discarded),
        "latest": latest,
        "upstream_backend": detect_upstream_backend(cwd),
        "session_files": {key: str(path) for key, path in session_paths(cwd).items()},
    }
    if compact and latest:
        payload["latest"] = {
            "status": latest.get("status"),
            "delta": latest.get("delta"),
            "metrics": latest.get("metrics", {}),
            "next_action_hint": (latest.get("asi") or {}).get("next_action_hint"),
        }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize a Ralph AutoResearch session.")
    add_common_args(parser)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    try:
        return print_result(summarize(args.cwd, args.compact))
    except Exception as exc:
        return fail_result(exc)


if __name__ == "__main__":
    raise SystemExit(main())
