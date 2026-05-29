#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re

from common import DEFAULT_BASELINE_POLICY, SUPPORTED_BASELINE_POLICIES, add_common_args, append_jsonl, assert_not_red, default_hard_gates, fail_result, load_scorecard_info, now_iso, print_result, required_entry_fields, resolve_cwd, session_paths


def slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "-", value.strip().lower()).strip("-")
    return text[:48] or "session"


def split_paths(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def segment_timestamp() -> str:
    return now_iso().replace(":", "").replace("+00:00", "Z").replace("+0000", "Z")


def setup_session(args: argparse.Namespace) -> dict:
    cwd = resolve_cwd(args.cwd)
    cwd.mkdir(parents=True, exist_ok=True)
    for label, value in (
        ("goal", args.goal),
        ("metric", args.metric),
        ("benchmark_command", args.benchmark_command),
        ("checks_command", args.checks_command),
        ("scope", args.scope),
    ):
        assert_not_red(label, value)
    scorecard_info = load_scorecard_info(args.scorecard)
    scorecard = scorecard_info["data"]
    paths = session_paths(cwd)
    segment_id = f"{slug(args.goal)}-{segment_timestamp()}"
    commit_paths = split_paths(args.commit_paths)
    config = {
        "entry_type": "config",
        "segment_id": segment_id,
        "scorecard_id": scorecard["id"],
        "scorecard_version": scorecard["version"],
        "scorecard_path": str(scorecard_info["path"]),
        "goal": args.goal,
        "metric": args.metric,
        "direction": args.direction,
        "benchmark_command": args.benchmark_command,
        "checks_command": args.checks_command,
        "scope": args.scope,
        "commit_paths": commit_paths,
        "baseline_policy": args.baseline_policy,
        "baseline_policy_source": "explicit" if args.baseline_policy != DEFAULT_BASELINE_POLICY else "default",
        "minimum_delta": args.minimum_delta,
        "generation_spine_enabled": bool(args.generation_spine),
    }
    entry = {
        **required_entry_fields(config, "config", None, default_hard_gates(True), {"hypothesis": "Session setup", "evidence": "Configuration recorded", "rollback_reason": "", "next_action_hint": "Run doctor, then next."}),
        **config,
    }
    paths["doc"].write_text(
        "\n".join(
            [
                f"# AutoResearch: {args.goal}",
                "",
                "## Objective",
                args.goal,
                "",
                "## Metric",
                f"- Primary: {args.metric} ({args.direction} is better)",
                f"- Baseline policy: {args.baseline_policy}",
                "",
                "## Scope",
                args.scope or "Not specified; keep edits explicitly scoped before logging keep decisions.",
                "",
                "## Commands",
                f"- Benchmark: `{args.benchmark_command}`",
                f"- Checks: `{args.checks_command or 'none configured'}`",
                "",
                "## Safety",
                "Codex main decides. Scorecards and gates decide keep/discard. RED content must not be logged.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    if not paths["ideas"].exists():
        paths["ideas"].write_text("# AutoResearch Ideas\n\n- [ ] Record the next scoped hypothesis after each packet.\n", encoding="utf-8")
    append_jsonl(paths["ledger"], entry)
    return {"ok": True, "cwd": str(cwd), "segment_id": segment_id, "files": {key: str(path) for key, path in paths.items()}, "scorecard": {"id": scorecard["id"], "version": scorecard["version"]}}


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or append a Ralph AutoResearch session config.")
    add_common_args(parser)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--metric", required=True)
    parser.add_argument("--direction", choices=("lower", "higher"), required=True)
    parser.add_argument("--benchmark-command", required=True)
    parser.add_argument("--checks-command", default=None)
    parser.add_argument("--scope", default="")
    parser.add_argument("--commit-paths", default="")
    parser.add_argument("--baseline-policy", choices=sorted(SUPPORTED_BASELINE_POLICIES), default=DEFAULT_BASELINE_POLICY)
    parser.add_argument("--minimum-delta", type=float, default=0.0)
    parser.add_argument("--generation-spine", action="store_true", help="Write manual generation evidence bundles from next.py.")
    parser.add_argument("--scorecard", default=None)
    args = parser.parse_args()
    try:
        return print_result(setup_session(args))
    except Exception as exc:
        return fail_result(exc)


if __name__ == "__main__":
    raise SystemExit(main())
