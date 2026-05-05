#!/usr/bin/env python3
from __future__ import annotations

import argparse

from common import add_common_args, default_hard_gates, direction_delta, fail_result, fingerprint, latest_baseline, latest_config, parse_metrics, print_result, read_ledger, resolve_cwd, run_shell, session_paths, write_json


def run_next(args: argparse.Namespace) -> dict:
    cwd = resolve_cwd(args.cwd)
    entries = read_ledger(cwd)
    config = latest_config(entries)
    command = args.command or config.get("benchmark_command")
    if not command:
        raise RuntimeError("missing benchmark command")
    result = run_shell(command, cwd, args.timeout)
    combined = f"{result.stdout}\n{result.stderr}"
    metrics = parse_metrics(combined)
    metric_name = config["metric"]
    metric_value = metrics.get(metric_name)
    checks_pass = True
    checks_result = None
    checks_command = args.checks_command if args.checks_command is not None else config.get("checks_command")
    if checks_command:
        checks = run_shell(checks_command, cwd, args.timeout)
        checks_result = {"returncode": checks.returncode}
        checks_pass = checks.returncode == 0
        combined = f"{combined}\n{checks.stdout}\n{checks.stderr}"
    baseline = latest_baseline(entries, metric_name)
    if baseline is None and metric_value is not None:
        baseline = metric_value
    hard_gates = default_hard_gates(result.returncode == 0 and checks_pass, combined)
    packet = {
        "ok": result.returncode == 0 and metric_value is not None and hard_gates["no_secret_leak"],
        "cwd": str(cwd),
        "segment_id": config["segment_id"],
        "command_returncode": result.returncode,
        "checks": checks_result,
        "metric": metric_name,
        "metrics": metrics,
        "primary_metric_present": metric_value is not None,
        "baseline": baseline,
        "delta": direction_delta(baseline, metric_value, config["direction"]) if metric_value is not None else None,
        "hard_gates": hard_gates,
        "freshness_fingerprint": fingerprint(cwd, config),
        "asi_template": {
            "hypothesis": "",
            "evidence": "",
            "rollback_reason": "",
            "next_action_hint": "",
            "lane": "",
            "family": "",
            "risk": "",
        },
    }
    write_json(session_paths(cwd)["last_run"], packet)
    return packet


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the next Ralph AutoResearch benchmark packet and cache last-run evidence.")
    add_common_args(parser)
    parser.add_argument("--command", default=None, help="Override the configured benchmark command for this packet.")
    parser.add_argument("--checks-command", default=None, help="Override the configured checks command for this packet.")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    try:
        return print_result(run_next(args))
    except Exception as exc:
        return fail_result(exc)


if __name__ == "__main__":
    raise SystemExit(main())
