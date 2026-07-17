#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path

from common import add_common_args, baseline_policy_from_config, direction_delta, fail_result, fingerprint, git_value, hard_gates_for_packet, latest_baseline, latest_config, parse_metrics, print_result, read_ledger, resolve_cwd, run_shell, session_paths, write_json
from generation import write_generation_bundle


NO_CANDIDATE_PATCH = "No candidate patch captured.\n"


def candidate_patch_for(cwd: Path) -> dict[str, object]:
    diff_stat = git_value(cwd, "diff", "--stat")
    if diff_stat:
        return {
            "content": diff_stat + "\n",
            "status": "captured",
            "reason": "tracked_diff_detected",
            "decision_required": True,
        }

    working_tree = git_value(cwd, "status", "--short")
    if working_tree:
        return {
            "content": "Working tree candidate changes:\n" + working_tree + "\n",
            "status": "captured",
            "reason": "working_tree_changes_detected",
            "decision_required": True,
        }

    reason = "working_tree_clean" if git_value(cwd, "rev-parse", "--is-inside-work-tree") == "true" else "not_git_repository"
    return {
        "content": NO_CANDIDATE_PATCH,
        "status": "no_candidate",
        "reason": reason,
        "decision_required": False,
    }


def metric_summary(packet: dict) -> str:
    metric_name = str(packet["metric"])
    metric_value = (packet.get("metrics") or {}).get(metric_name)
    return f"{metric_name}={metric_value if metric_value is not None else 'missing'}"


def metrics_summary(packet: dict) -> str:
    metrics = packet.get("metrics") or {}
    if not metrics:
        return "none"
    return ", ".join(f"{name}={value}" for name, value in sorted(metrics.items()))


def gate_summary(packet: dict) -> str:
    failed = [name for name, passed in sorted((packet.get("hard_gates") or {}).items()) if passed is not True]
    return "all true" if not failed else "failed: " + ", ".join(failed)


def build_asi(config: dict, packet: dict, candidate: dict[str, object]) -> dict[str, str]:
    goal = str(config.get("goal") or "the configured AutoResearch goal")
    candidate_status = str(candidate["status"])
    candidate_reason = str(candidate["reason"])
    evidence = (
        f"candidate_patch={candidate_status} ({candidate_reason}); "
        f"metrics={metrics_summary(packet)}; baseline={packet.get('baseline')}; "
        f"delta={packet.get('delta')}; hard_gates={gate_summary(packet)}."
    )
    if candidate_status == "no_candidate":
        return {
            "hypothesis": f"The configured benchmark and gates provide valid harness evidence for the goal: {goal}.",
            "evidence": evidence,
            "rollback_reason": "No candidate patch was evaluated, so no rollback is required.",
            "next_action_hint": "Treat this packet as harness evidence only; create a scoped candidate before any keep/discard decision.",
            "lane": "local",
            "family": "autoresearch",
            "risk": "harness_only",
        }
    return {
        "hypothesis": f"The captured candidate may improve the configured goal: {goal}.",
        "evidence": evidence,
        "rollback_reason": "Revert the scoped candidate changes if validation fails or the candidate is discarded.",
        "next_action_hint": "Review the candidate evidence, metric delta, and hard gates before logging a keep/discard decision.",
        "lane": "local",
        "family": "autoresearch",
        "risk": "candidate_requires_review",
    }


def build_improvement(config: dict, packet: dict, candidate: dict[str, object]) -> str:
    candidate_status = str(candidate["status"])
    candidate_reason = str(candidate["reason"])
    if candidate_status == "no_candidate":
        recommendation_status = "harness-only"
        recommendation = (
            "This is a harness-only packet. No keep/discard decision is applicable until a candidate patch is present."
        )
        risk = "The measurements validate the harness only; they do not demonstrate an implemented improvement."
        validation = "Create a scoped candidate, rerun the same benchmark and gates, then compare the resulting delta."
    else:
        recommendation_status = "candidate-review-required"
        recommendation = "Review the candidate, metric delta, and hard gates before logging any keep/discard decision."
        risk = "A captured working-tree summary identifies candidate scope but is not proof that the behavior is correct."
        validation = "Inspect the scoped changes and run the validation required by the target repository before deciding."
    return "\n".join(
        [
            "# AutoResearch Packet Synthesis",
            "",
            f"- Goal: {config.get('goal') or 'configured AutoResearch goal'}",
            f"- Recommendation status: {recommendation_status}",
            f"- Candidate patch: `{candidate_status}` ({candidate_reason})",
            f"- Primary metric: `{metric_summary(packet)}`",
            f"- Emitted metrics: {metrics_summary(packet)}",
            f"- Baseline: {packet.get('baseline')}",
            f"- Delta: {packet.get('delta')}",
            f"- Hard gates: {gate_summary(packet)}",
            "",
            "## Evidence",
            "The packet completed the configured benchmark and checks and captured their metric and hard-gate results.",
            "",
            "## Expected Benefit",
            "The generation bundle is self-explanatory: it distinguishes harness validation from an evaluated candidate and carries actionable ASI.",
            "",
            "## Risk",
            risk,
            "",
            "## Validation Needed",
            validation,
            "",
            "## Recommendation",
            recommendation,
            "",
        ]
    )


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
    candidate = candidate_patch_for(cwd)
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
        "candidate_patch": {
            "status": candidate["status"],
            "reason": candidate["reason"],
            "decision_required": candidate["decision_required"],
        },
    }
    packet["asi_template"] = build_asi(config, packet, candidate)
    if config.get("generation_spine_enabled") or os.environ.get("RALPH_AUTORESEARCH_GENERATION_SPINE") == "1":
        packet["generation"] = write_generation_bundle(
            cwd,
            config["segment_id"],
            {
                "candidate_patch": candidate["content"],
                "stdout": result.stdout,
                "stderr": result.stderr,
                "improvement": build_improvement(config, packet, candidate),
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
                    "candidate_patch_status": candidate["status"],
                    "decision_required": candidate["decision_required"],
                    "reason": "candidate_review_pending" if candidate["decision_required"] else "no_candidate_patch",
                },
                "asi": packet["asi_template"],
                "trace": {
                    "freshness_fingerprint": packet["freshness_fingerprint"],
                    "primary_metric_present": packet["primary_metric_present"],
                    "candidate_patch_status": candidate["status"],
                    "candidate_patch_reason": candidate["reason"],
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
