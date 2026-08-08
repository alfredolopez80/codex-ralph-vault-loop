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


def inspect(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        counts = handler_counts(root)
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        return {"root": str(root), "errors": [f"hooks_config:{type(exc).__name__}"], "warnings": [], "handler_counts": {}}
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
    profile = root / ".codex" / "hooks" / "shared" / "runtime_profile.py"
    if profile.is_file():
        text = profile.read_text(encoding="utf-8")
        for marker, limit in (("prompt_context_bytes_hard=1_800", 1800), ("prompt_context_bytes_hard=800", 800)):
            match = re.search(re.escape(marker), text)
            if match is None:
                warnings.append(f"profile_marker_not_found:{marker}")
        if "max_stop_continuations=1" not in text:
            errors.append("stop_continuation_cap_missing")
    else:
        warnings.append("runtime_profile_not_available")
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
    return {"root": str(root), "handler_counts": counts, "errors": sorted(set(errors)), "warnings": sorted(set(warnings)), "status": "failed" if errors else "passed"}


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
    report: dict[str, Any] = {"schema_version": 1, "candidate": candidate}
    if args.baseline_root:
        report = compare(inspect(args.baseline_root.resolve()), candidate)
        report["schema_version"] = 1
    if args.baseline_benchmark and args.candidate_benchmark:
        benchmark = compare_benchmark_reports(
            args.baseline_benchmark.resolve(), args.candidate_benchmark.resolve(), args.benchmark_noise_threshold
        )
        report["benchmark"] = benchmark
        if benchmark.get("classification") != "mejora" and benchmark.get("classification") != "ruido":
            report.setdefault("errors", []).append("benchmark_not_comparable" if benchmark.get("classification") == "cambio no comparable" else "benchmark_regression")
            report["errors"] = sorted(set(report["errors"]))
            report["status"] = "failed"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report.get("status") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
