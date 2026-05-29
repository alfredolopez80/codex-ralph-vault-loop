#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os

from common import add_common_args, baseline_policy_from_config, direction_delta, fail_result, fingerprint, git_value, hard_gates_for_packet, latest_baseline, latest_config, parse_metrics, print_result, read_ledger, resolve_cwd, run_shell, session_paths, write_json
from generation import write_generation_bundle


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
    baseline_policy = baseline_policy_from_config(config)
    baseline = latest_baseline(entries, metric_name, config["direction"], baseline_policy)
    if baseline is None and metric_value is not None:
        baseline = metric_value
    hard_gates = hard_gates_for_packet(cwd, config, result.returncode == 0 and checks_pass, combined, metric_value)
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
        "baseline_policy": baseline_policy,
        "baseline_policy_source": config.get("baseline_policy_source", "default"),
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
    if config.get("generation_spine_enabled") or os.environ.get("RALPH_AUTORESEARCH_GENERATION_SPINE") == "1":
        packet["generation"] = write_generation_bundle(
            cwd,
            config["segment_id"],
            {
                "candidate_patch": git_value(cwd, "diff", "--stat") or "No candidate patch captured.\n",
                "stdout": result.stdout,
                "stderr": result.stderr,
                "command": {
                    "benchmark_command": command,
                    "checks_command": checks_command or "",
                    "timeout": args.timeout,
                    "cwd": str(cwd),
                    "env_allowlist": ["PYTHONDONTWRITEBYTECODE", "RALPH_AUTORESEARCH_GENERATION_SPINE"],
                },
                "metrics": metrics,
                "checks": {"benchmark_returncode": result.returncode, "checks": checks_result},
                "hard_gates": hard_gates,
                "decision": {
                    "status": "pending",
                    "delta": packet["delta"],
                    "baseline": baseline,
                    "baseline_policy": baseline_policy,
                },
                "asi": packet["asi_template"],
                "trace": {
                    "freshness_fingerprint": packet["freshness_fingerprint"],
                    "primary_metric_present": packet["primary_metric_present"],
                    "output_preview_bytes": 65_536,
                },
            },
        )
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
