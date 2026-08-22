#!/usr/bin/env python3
"""Structural regression gate for the runtime optimization sequence."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "SubagentStart", "SubagentStop", "Stop")
REQUIRED_INVARIANTS = ("Codex main", "External models advise", "RED", "evidence", "Implementation notes")
EXPECTED_HANDLER_COUNTS = {event: 1 for event in EVENTS}
SECURITY_ONLY_HANDLER_COUNTS = {"PreToolUse": 1}
CONSOLIDATED_HANDLERS = {
    "SessionStart": "session_start_dispatch.py",
    "UserPromptSubmit": "user_prompt_dispatch.py",
    "PreToolUse": "pre_tool_dispatch.py",
    "PostToolUse": "post_tool_dispatch.py",
    "Stop": "stop_dispatch.py",
}
EXPECTED_SCENARIOS = {
    "small_read_only",
    "small_edit",
    "medium_edit_test",
    "repeated_prompt",
    "session_start_startup",
    "session_start_compact",
    "stop_allow",
    "stop_objective_failure",
    "subagent_route",
    "red_safety",
}
EXPECTED_PROFILES = {"luna", "sol", "conservative_unknown"}
PROFILE_CAPS = {
    "luna": {"prompt": 1800, "session": 2200},
    "sol": {"prompt": 800, "session": 800},
    "conservative_unknown": {"prompt": 2200, "session": 2200},
}


def hooks(root: Path) -> dict[str, list[dict[str, Any]]]:
    value = json.loads((root / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    return value.get("hooks", {})


def handler_counts(root: Path) -> dict[str, int]:
    config = hooks(root)
    result: dict[str, int] = {}
    for event in EVENTS:
        groups = config.get(event, [])
        result[event] = sum(len(group.get("hooks", [])) for group in groups if isinstance(group, dict) and isinstance(group.get("hooks", []), list))
    return result


def is_security_only_config(config: dict[str, list[dict[str, Any]]]) -> bool:
    """Recognize the explicitly versioned #84 registration profile."""
    if set(config) != {"PreToolUse"}:
        return False
    groups = config.get("PreToolUse", [])
    if len(groups) != 1 or not isinstance(groups[0], dict):
        return False
    handlers = groups[0].get("hooks", [])
    if not isinstance(handlers, list) or len(handlers) != 1 or not isinstance(handlers[0], dict):
        return False
    return "security_pre_tool_dispatch.py" in str(handlers[0].get("command", ""))


def _security_only_registration_errors(config: dict[str, list[dict[str, Any]]]) -> list[str]:
    errors: list[str] = []
    groups = config.get("PreToolUse", [])
    if len(groups) != 1 or not isinstance(groups[0], dict):
        return ["security_only_pre_tool_group"]
    matcher = groups[0].get("matcher")
    required_aliases = ("Bash", "exec_command", "apply_patch", "Edit", "Write", "Agent", "spawn_agent", "mcp__fixture")
    try:
        if not isinstance(matcher, str) or any(re.fullmatch(matcher, alias) is None for alias in required_aliases):
            errors.append("security_only_pre_tool_matcher_coverage")
    except re.error:
        errors.append("security_only_pre_tool_matcher_coverage")
    handlers = groups[0].get("hooks", [])
    command = str(handlers[0].get("command", "")) if isinstance(handlers, list) and handlers else ""
    if "security_pre_tool_dispatch.py" not in command:
        errors.append("security_only_dispatcher_target")
    return errors


def _profile_caps(root: Path) -> tuple[dict[str, int], list[str]]:
    path = root / ".codex" / "hooks" / "shared" / "runtime_profile.py"
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return {}, ["runtime_profile_not_available"]
    caps: dict[str, int] = {}
    errors: list[str] = []
    for constant, profile in (
        ("LUNA", "luna"),
        ("SOL", "sol"),
        ("CONSERVATIVE_UNKNOWN", "conservative_unknown"),
    ):
        match = re.search(rf"{constant}\s*=\s*RuntimeProfile\((.*?)\n\)", source, re.DOTALL)
        if match is None:
            errors.append(f"runtime_profile_missing:{profile}")
            continue
        block = match.group(1)
        for field, suffix in (("prompt_context_bytes_hard", "prompt"), ("session_context_bytes_hard", "session")):
            value = re.search(rf"{field}\s*=\s*([0-9_]+)", block)
            if value is None:
                errors.append(f"runtime_profile_cap_missing:{profile}:{suffix}")
                continue
            caps[f"{profile}_{suffix}"] = int(value.group(1).replace("_", ""))
        continuation = re.search(r"max_stop_continuations\s*=\s*([0-9_]+)", block)
        if continuation is None or int(continuation.group(1).replace("_", "")) != 1:
            errors.append(f"stop_continuation_cap:{profile}")
    return caps, errors


def _matcher_and_dispatch_errors(config: dict[str, list[dict[str, Any]]]) -> list[str]:
    errors: list[str] = []
    for event, groups in config.items():
        if not isinstance(groups, list):
            errors.append(f"hook_groups_invalid:{event}")
            continue
        for group in groups:
            if not isinstance(group, dict):
                errors.append(f"hook_group_invalid:{event}")
                continue
            matcher = group.get("matcher")
            if matcher is not None:
                try:
                    re.compile(str(matcher))
                except re.error:
                    errors.append(f"matcher_malformed:{event}")
            if event in {"UserPromptSubmit", "Stop"} and matcher is not None:
                errors.append(f"unsupported_matcher:{event}")
    for event, expected in CONSOLIDATED_HANDLERS.items():
        groups = config.get(event, [])
        commands = [
            str(handler.get("command", ""))
            for group in groups
            if isinstance(group, dict)
            for handler in group.get("hooks", [])
            if isinstance(handler, dict)
        ]
        if len(commands) != 1 or expected not in commands[0]:
            errors.append(f"dispatcher_target:{event}")
    session_groups = config.get("SessionStart", [])
    session_matcher = session_groups[0].get("matcher") if len(session_groups) == 1 and isinstance(session_groups[0], dict) else None
    if not isinstance(session_matcher, str) or set(session_matcher.split("|")) != {"startup", "resume", "clear", "compact"}:
        errors.append("session_start_matcher")
    pre_groups = config.get("PreToolUse", [])
    pre_matcher = pre_groups[0].get("matcher") if len(pre_groups) == 1 and isinstance(pre_groups[0], dict) else ""
    required_aliases = ("Bash", "exec_command", "apply_patch", "Edit", "Write", "Agent", "spawn_agent", "mcp__fixture")
    try:
        if not isinstance(pre_matcher, str) or any(re.fullmatch(pre_matcher, alias) is None for alias in required_aliases):
            errors.append("pre_tool_matcher_coverage")
    except re.error:
        errors.append("pre_tool_matcher_coverage")
    return errors


def inspect(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        config = hooks(root)
        counts = handler_counts(root)
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        return {"root": str(root), "errors": [f"hooks_config:{type(exc).__name__}"], "warnings": [], "handler_counts": {}}
    security_only = is_security_only_config(config)
    if security_only:
        if counts.get("PreToolUse") != SECURITY_ONLY_HANDLER_COUNTS["PreToolUse"]:
            errors.append("handler_target:PreToolUse")
        errors.extend(_security_only_registration_errors(config))
    else:
        for event, expected in EXPECTED_HANDLER_COUNTS.items():
            if counts.get(event) != expected:
                errors.append(f"handler_target:{event}")
        errors.extend(_matcher_and_dispatch_errors(config))
    agents = root / "AGENTS.md"
    if not agents.is_file() or len(agents.read_bytes()) > 14 * 1024:
        errors.append("agents_instruction_hard_cap")
    else:
        content = agents.read_text(encoding="utf-8")
        errors.extend(f"missing_invariant:{marker}" for marker in REQUIRED_INVARIANTS if marker.lower() not in content.lower())
    try:
        data = tomllib.loads((root / ".codex" / "config.toml").read_text(encoding="utf-8"))
        agents_config = data.get("agents", {})
        if agents_config.get("max_threads") != 2:
            errors.append("max_threads_changed")
        if agents_config.get("max_depth") != 1:
            errors.append("max_depth_changed")
    except (OSError, tomllib.TOMLDecodeError, TypeError):
        errors.append("config_unreadable")
    context_caps, profile_errors = _profile_caps(root)
    errors.extend(profile_errors)
    for profile_name, limits in PROFILE_CAPS.items():
        for kind, maximum in limits.items():
            value = context_caps.get(f"{profile_name}_{kind}")
            if value is not None and (value <= 0 or value > maximum):
                errors.append(f"runtime_profile_cap:{profile_name}:{kind}")
    continuation = root / ".codex" / "hooks" / "shared" / "continuation_budget.py"
    try:
        continuation_source = continuation.read_text(encoding="utf-8")
    except OSError:
        errors.append("stop_continuation_gate_missing")
    else:
        if "count == 0 or (count == 1 and critical" not in continuation_source:
            errors.append("stop_continuation_gate_missing")
    try:
        mcp = tomllib.loads((root / ".codex" / "config.toml").read_text(encoding="utf-8")).get("mcp_servers", {})
        active = {name: value for name, value in mcp.items() if isinstance(value, dict) and value.get("enabled") is not False and value.get("disabled") is not True}
        endpoints: dict[str, list[str]] = {}
        schemas: dict[str, list[str]] = {}
        for name, value in active.items():
            endpoint = json.dumps({key: value.get(key) for key in ("url", "command", "args", "cwd")}, sort_keys=True)
            endpoints.setdefault(endpoint, []).append(name)
            for tool in value.get("enabled_tools", []) if isinstance(value.get("enabled_tools", []), list) else []:
                schemas.setdefault(endpoint + ":" + str(tool), []).append(name)
        if any(len(names) > 1 for names in endpoints.values()) or any(len(names) > 1 for names in schemas.values()):
            errors.append("mcp_duplicate_active")
    except (OSError, tomllib.TOMLDecodeError, TypeError):
        errors.append("mcp_config_unreadable")
    return {
        "root": str(root),
        "profile": "security-only" if security_only else "legacy-lifecycle",
        "handler_counts": counts,
        "context_hard_caps": context_caps,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "status": "failed" if errors else "passed",
    }


def compare(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    errors = list(candidate.get("errors", []))
    for event, count in candidate.get("handler_counts", {}).items():
        if count > baseline.get("handler_counts", {}).get(event, count):
            errors.append(f"handler_count_increased:{event}")
    return {"status": "failed" if errors else "passed", "errors": sorted(set(errors)), "baseline": baseline, "candidate": candidate}


def compare_benchmark_reports(baseline_path: Path, candidate_path: Path, threshold: float) -> dict[str, Any]:
    """Use the schema-aware benchmark comparator as an optional hard gate."""
    comparator_path = Path(__file__).resolve().parents[1] / "evals" / "compare_hook_benchmarks.py"
    spec = importlib.util.spec_from_file_location("runtime_benchmark_comparator", comparator_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("benchmark comparator is unavailable")
    comparator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(comparator)
    try:
        baseline_report = comparator._load(baseline_path)
        candidate_report = comparator._load(candidate_path)
    except comparator.IncompatibleReport as exc:
        return {"classification": "cambio no comparable", "error": str(exc)}
    return comparator.compare(baseline_report, candidate_report, threshold)


def load_benchmark_report(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read benchmark report: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"benchmark report is not an object: {path}")
    return value


def benchmark_hard_errors(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("schema_version") != 2:
        errors.append("benchmark_schema")
    if report.get("subscription_usage_measured") is not False:
        errors.append("benchmark_subscription_usage_claim")
    counts = report.get("configured_handlers_by_event")
    if not isinstance(counts, dict):
        errors.append("benchmark_handler_counts_missing")
    else:
        if counts == SECURITY_ONLY_HANDLER_COUNTS:
            benchmark_profile = "security-only"
        else:
            benchmark_profile = "legacy-lifecycle"
            for event, expected in EXPECTED_HANDLER_COUNTS.items():
                if counts.get(event) != expected:
                    errors.append(f"benchmark_handler_target:{event}")
        if benchmark_profile == "security-only" and set(counts) != set(SECURITY_ONLY_HANDLER_COUNTS):
            errors.append("benchmark_security_only_handler_target")
    matrix = report.get("scenario_matrix")
    if not isinstance(matrix, list):
        return sorted(set([*errors, "benchmark_matrix_missing"]))
    identities = [
        (case.get("scenario"), case.get("profile"))
        for case in matrix
        if isinstance(case, dict)
    ]
    expected_identities = {(scenario, profile) for scenario in EXPECTED_SCENARIOS for profile in EXPECTED_PROFILES}
    if len(identities) != len(set(identities)) or set(identities) != expected_identities:
        errors.append("benchmark_matrix_incomplete")
    for raw_case in matrix:
        if not isinstance(raw_case, dict):
            errors.append("benchmark_case_invalid")
            continue
        profile = raw_case.get("profile")
        scenario = raw_case.get("scenario")
        if raw_case.get("subscription_usage_measured") is not False:
            errors.append("benchmark_case_subscription_usage_claim")
        for field in ("configured_handler_count", "matched_handler_count", "executed_handler_count", "process_count"):
            if not isinstance(raw_case.get(field), int) or int(raw_case[field]) < 0:
                errors.append(f"benchmark_case_field:{field}")
        if isinstance(raw_case.get("executed_handler_count"), int) and isinstance(raw_case.get("matched_handler_count"), int):
            if raw_case["executed_handler_count"] > raw_case["matched_handler_count"]:
                errors.append("benchmark_execution_exceeds_match")
        if raw_case.get("process_count") != raw_case.get("executed_handler_count"):
            errors.append("benchmark_process_attribution")
        if profile in PROFILE_CAPS:
            if scenario == "repeated_prompt" and int(raw_case.get("output_bytes_max", 2**31)) > PROFILE_CAPS[profile]["prompt"]:
                errors.append(f"benchmark_context_cap:{profile}")
            if str(scenario).startswith("session_start_") and int(raw_case.get("output_bytes_max", 2**31)) > PROFILE_CAPS[profile]["session"]:
                errors.append(f"benchmark_session_cap:{profile}")
        if str(scenario).startswith("session_start_") and benchmark_profile != "security-only":
            if raw_case.get("child_process_count_measured") is not True or raw_case.get("child_process_count") != 0:
                errors.append("benchmark_session_child_process")
        if scenario == "stop_allow" and int(raw_case.get("continuation_count", 0)) != 0:
            errors.append("benchmark_stop_allow_continuation")
        if scenario == "stop_objective_failure" and int(raw_case.get("continuation_count", 0)) > 1:
            errors.append("benchmark_stop_loop")
        if scenario == "red_safety" and benchmark_profile != "security-only":
            if int(raw_case.get("block_count", 0)) < 1:
                errors.append("benchmark_red_not_blocked")
            if raw_case.get("child_process_count_measured") is not True or raw_case.get("child_process_count") != 0:
                errors.append("benchmark_red_child_process")
    if report.get("successful_post_tool_stdout_chars") != 0:
        errors.append("benchmark_post_allow_stdout")
    if report.get("successful_stop_stdout_chars") != 0:
        errors.append("benchmark_stop_allow_stdout")
    return sorted(set(errors))


def benchmark_performance_warnings(comparison: dict[str, Any]) -> list[str]:
    classification = comparison.get("classification")
    if classification == "regresión":
        return ["benchmark_regression"]
    if classification == "cambio no comparable":
        return ["benchmark_not_comparable"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", type=Path, default=Path.cwd())
    parser.add_argument("--baseline-root", type=Path)
    parser.add_argument("--baseline-benchmark", type=Path)
    parser.add_argument("--candidate-benchmark", type=Path)
    parser.add_argument("--benchmark-noise-threshold", type=float, default=0.05)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)
    if bool(args.baseline_benchmark) != bool(args.candidate_benchmark):
        parser.error("--baseline-benchmark and --candidate-benchmark must be supplied together")
    if not 0 <= args.benchmark_noise_threshold <= 1:
        parser.error("--benchmark-noise-threshold must be between 0 and 1")
    candidate = inspect(args.candidate_root.resolve())
    report: dict[str, Any] = {"schema_version": 1, "candidate": candidate, "status": candidate.get("status", "failed")}
    report["errors"] = list(candidate.get("errors", []))
    report["warnings"] = list(candidate.get("warnings", []))
    if args.baseline_root:
        report = compare(inspect(args.baseline_root.resolve()), candidate)
        report["schema_version"] = 1
    if args.baseline_benchmark and args.candidate_benchmark:
        try:
            candidate_benchmark = load_benchmark_report(args.candidate_benchmark.resolve())
            hard_errors = benchmark_hard_errors(candidate_benchmark)
        except ValueError:
            hard_errors = ["benchmark_candidate_unreadable"]
        if hard_errors:
            report.setdefault("errors", []).extend(hard_errors)
            report["errors"] = sorted(set(report["errors"]))
            report["status"] = "failed"
        benchmark = compare_benchmark_reports(
            args.baseline_benchmark.resolve(), args.candidate_benchmark.resolve(), args.benchmark_noise_threshold
        )
        report["benchmark"] = benchmark
        report.setdefault("warnings", []).extend(benchmark_performance_warnings(benchmark))
        report["warnings"] = sorted(set(report["warnings"]))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report.get("status") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
