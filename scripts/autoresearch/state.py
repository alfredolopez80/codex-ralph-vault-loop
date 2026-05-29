#!/usr/bin/env python3
from __future__ import annotations

import argparse

from common import add_common_args, baseline_policy_from_config, detect_upstream_backend, direction_delta, fail_result, latest_baseline, latest_config, print_result, read_ledger, resolve_cwd, session_paths


def summarize(cwd_raw: str | None, compact: bool) -> dict:
    cwd = resolve_cwd(cwd_raw)
    entries = read_ledger(cwd)
    config = latest_config(entries)
    packets = [entry for entry in entries if entry.get("entry_type") == "packet"]
    kept = [entry for entry in packets if entry.get("status") == "keep"]
    discarded = [entry for entry in packets if entry.get("status") == "discard"]
    latest = packets[-1] if packets else None
    baseline_policy = baseline_policy_from_config(config)
    best_kept_baseline = latest_baseline(entries, config["metric"], config["direction"], "best_kept")
    latest_kept_baseline = latest_baseline(entries, config["metric"], config["direction"], "latest_kept")
    initial_baseline = latest_baseline(entries, config["metric"], config["direction"], "initial")
    latest_metric = ((latest or {}).get("metrics") or {}).get(config["metric"])
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
        "baseline_policy": baseline_policy,
        "baseline_policy_source": config.get("baseline_policy_source", "default"),
        "minimum_delta": config.get("minimum_delta", 0.0),
        "baselines": {
            "initial": initial_baseline,
            "latest_kept": latest_kept_baseline,
            "best_kept": best_kept_baseline,
        },
        "current_delta": direction_delta(best_kept_baseline, latest_metric, config["direction"]) if latest_metric is not None else None,
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
