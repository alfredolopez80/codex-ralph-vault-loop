#!/usr/bin/env python3
"""Compare two schema-versioned local hook benchmark reports.

The comparison is intentionally a runtime/observability comparison. It never
claims subscription token or credit usage, and it treats safety/output
contract changes as non-comparable rather than silently converting them into a
performance score.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 2
DEFAULT_NOISE_THRESHOLD = 0.05
IDENTITY_FIELDS = ("event", "role", "scenario", "effective_config", "source_scope")
LOWER_IS_BETTER = (
    "runtime_p50_ms",
    "runtime_p95_ms",
    "matched_handler_count",
    "executed_handler_count",
    "output_bytes",
    "estimated_context_units",
    "persisted_bytes_delta",
)
SEMANTIC_FIELDS = ("block_count", "continuation_count", "child_process_count")


class IncompatibleReport(ValueError):
    """Raised when a report cannot be compared safely."""


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IncompatibleReport(f"cannot read JSON report: {path}") from exc
    if not isinstance(value, dict):
        raise IncompatibleReport(f"report must be a JSON object: {path}")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise IncompatibleReport(
            f"incompatible schema_version in {path}: expected {SCHEMA_VERSION}, got {value.get('schema_version')!r}"
        )
    if value.get("subscription_usage_measured") is not False:
        raise IncompatibleReport(f"report does not have subscription_usage_measured=false: {path}")
    cases = value.get("cases")
    if not isinstance(cases, list) or not cases:
        raise IncompatibleReport(f"report has no cases: {path}")
    for case in cases:
        if not isinstance(case, dict) or not all(isinstance(case.get(key), str) for key in ("event", "role", "effective_config", "source_scope")):
            raise IncompatibleReport(f"report contains an invalid case identity: {path}")
    return value


def _identity(case: Mapping[str, Any]) -> tuple[str, ...]:
    scenario = case.get("scenario", case.get("payload", ""))
    return tuple(str(case.get(key, scenario if key == "scenario" else "")) for key in IDENTITY_FIELDS)


def _numeric(case: Mapping[str, Any], key: str) -> float | None:
    value = case.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    return float(value)


def _relative_delta(baseline: float, candidate: float) -> float:
    denominator = max(abs(baseline), 1.0)
    return (candidate - baseline) / denominator


def _classification(delta: float, *, lower_is_better: bool, threshold: float) -> str:
    if abs(delta) <= threshold:
        return "ruido"
    improved = delta < 0 if lower_is_better else delta > 0
    return "mejora" if improved else "regresión"


def compare(baseline: Mapping[str, Any], candidate: Mapping[str, Any], threshold: float) -> dict[str, Any]:
    baseline_cases = {_identity(case): case for case in baseline["cases"] if isinstance(case, dict)}
    candidate_cases = {_identity(case): case for case in candidate["cases"] if isinstance(case, dict)}
    shared = sorted(set(baseline_cases) & set(candidate_cases))
    if not shared:
        return {"classification": "cambio no comparable", "reason": "no shared case identities", "cases": []}

    rows: list[dict[str, Any]] = []
    semantic_changes: list[dict[str, Any]] = []
    for identity in shared:
        before = baseline_cases[identity]
        after = candidate_cases[identity]
        metrics: dict[str, dict[str, Any]] = {}
        for key in LOWER_IS_BETTER:
            old = _numeric(before, key)
            new = _numeric(after, key)
            if old is None or new is None:
                continue
            delta = _relative_delta(old, new)
            metrics[key] = {
                "baseline": old,
                "candidate": new,
                "relative_delta": round(delta, 6),
                "classification": _classification(delta, lower_is_better=True, threshold=threshold),
            }
        for key in SEMANTIC_FIELDS:
            old = _numeric(before, key)
            new = _numeric(after, key)
            if old is not None and new is not None and old != new:
                semantic_changes.append({"case": identity, "metric": key, "baseline": old, "candidate": new})
        rows.append({"case": identity, "metrics": metrics})

    classifications = [
        metric["classification"]
        for row in rows
        for metric in row["metrics"].values()
        if metric["classification"] != "ruido"
    ]
    if semantic_changes:
        overall = "cambio no comparable"
        reason = "objective output or process semantics changed"
    elif not classifications:
        overall = "ruido"
        reason = f"all comparable deltas are within the {threshold:.3g} threshold"
    elif "regresión" in classifications and "mejora" in classifications:
        overall = "cambio no comparable"
        reason = "candidate trades improvements against regressions"
    elif "regresión" in classifications:
        overall = "regresión"
        reason = "one or more lower-is-better metrics regressed"
    else:
        overall = "mejora"
        reason = "one or more lower-is-better metrics improved"
    return {
        "schema_version": SCHEMA_VERSION,
        "classification": overall,
        "reason": reason,
        "noise_threshold": threshold,
        "shared_case_count": len(shared),
        "missing_from_candidate": [list(item) for item in sorted(set(baseline_cases) - set(candidate_cases))],
        "new_in_candidate": [list(item) for item in sorted(set(candidate_cases) - set(baseline_cases))],
        "semantic_changes": semantic_changes,
        "cases": rows,
        "subscription_usage_measured": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two local hook benchmark JSON reports.")
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--noise-threshold", "--threshold", dest="threshold", type=float, default=DEFAULT_NOISE_THRESHOLD)
    args = parser.parse_args()
    if not math.isfinite(args.threshold) or args.threshold < 0 or args.threshold > 1:
        parser.error("--noise-threshold must be between 0 and 1")
    try:
        result = compare(_load(args.baseline), _load(args.candidate), args.threshold)
    except IncompatibleReport as exc:
        print(json.dumps({"classification": "cambio no comparable", "error": str(exc)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if result.get("classification") == "regresión" else 0


if __name__ == "__main__":
    raise SystemExit(main())
