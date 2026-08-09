"""Aggregate isolated hook scenario samples into schema-v2 rows."""
from __future__ import annotations

import statistics
from pathlib import Path
from typing import Mapping

from hook_benchmark_scenarios import PROFILES, SCENARIOS, Sample, percentile, run_sample


TOOL_METADATA = {
    "small_read_only": ("exec_command", "read"),
    "small_edit": ("apply_patch", "write"),
    "medium_edit_test": ("apply_patch+exec_command", "write+test"),
    "subagent_route": ("spawn_agent", "agent"),
    "red_safety": ("mcp__remote__send", "external_mcp"),
}


def _median(samples: list[Sample], field: str) -> int:
    return int(statistics.median(int(getattr(sample, field)) for sample in samples))


def _case(scenario: str, profile: str, model: str, family: str, samples: list[Sample]) -> dict[str, object]:
    durations = [sample.runtime_ms for sample in samples]
    outputs = [sample.output_bytes for sample in samples]
    children = [sample.child_count for sample in samples]
    measured_children = all(value is not None for value in children)
    first = samples[0]
    median_output = int(statistics.median(outputs))
    tool_name, tool_family = TOOL_METADATA.get(scenario, ("none", "none"))
    return {
        "schema_version": 2,
        "scenario": scenario,
        "profile": profile,
        "model": model,
        "model_family": family,
        "event": "+".join(first.events),
        "role": "+".join(first.roles) or "matcher_skip",
        "tool_name": tool_name,
        "tool_family": tool_family,
        "effective_config": "project_only",
        "source_scope": "project",
        "configured_handler_count": first.configured,
        "matched_handler_count": _median(samples, "matched"),
        "executed_handler_count": _median(samples, "executed"),
        "process_count": _median(samples, "executed"),
        "child_process_count": int(statistics.median(value for value in children if value is not None)) if measured_children else None,
        "child_process_count_measured": measured_children,
        "known_subprocesses": ["task_intake", "recall"] if scenario == "repeated_prompt" and any((value or 0) > 0 for value in children) else [],
        "skipped_reason": list(first.skipped_reasons) if first.matched else ["matcher_miss"],
        "components_considered": list(first.components_considered),
        "components_executed": list(first.components_executed),
        "components_skipped": list(first.components_skipped),
        "runtime_wall_ms": round(statistics.median(durations), 3),
        "runtime_p50_ms": round(statistics.median(durations), 3),
        "runtime_p95_ms": round(percentile(durations, 95), 3),
        "p50_ms": round(statistics.median(durations), 3),
        "p95_ms": round(percentile(durations, 95), 3),
        "output_bytes": median_output,
        "output_bytes_max": max(outputs),
        "stdout_chars": median_output,
        "estimated_context_units": (median_output + 3) // 4,
        "block_count": _median(samples, "blocks"),
        "continuation_count": _median(samples, "continuations"),
        "persisted_bytes_delta": _median(samples, "persisted_delta"),
        "persisted_bytes": _median(samples, "persisted_delta"),
        "cache_hits": _median(samples, "cache_hits"),
        "advisor_count": _median(samples, "advisor_count"),
        "subscription_usage_measured": False,
    }


def measure_scenarios(config: Mapping[str, object], root: Path, iterations: int, warmup: int) -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for scenario in SCENARIOS:
        for profile, (model, family) in PROFILES.items():
            for index in range(warmup):
                run_sample(config, root, scenario, profile, f"warmup-{scenario}-{profile}-{index}")
            samples = [
                run_sample(config, root, scenario, profile, f"measured-{scenario}-{profile}-{index}")
                for index in range(iterations)
            ]
            cases.append(_case(scenario, profile, model, family, samples))
    return cases


__all__ = ["measure_scenarios"]
