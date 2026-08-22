#!/usr/bin/env python3
"""Capture a comparison-safe #81 native execution baseline.

The collector keeps SECURITY_BASELINE evidence and native productivity
observations separate. Missing observations remain explicit null values; they
are never normalized to zero.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _eval_common import detect_secret_leak, load_scorecard, write_json


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "config" / "secure-native-baseline.toml"
MAX_INPUT_BYTES = 2 * 1024 * 1024
SECURITY_ARTIFACT_KEYS = (
    "security_contract",
    "security_runner",
    "project_dispatcher",
    "project_hook_config",
    "global_dispatcher",
    "global_hook_config",
    "effective_graph_runner",
)


class BaselineError(ValueError):
    """Raised when a capture cannot be compared safely."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
            raise BaselineError(f"input must be a bounded regular file: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BaselineError(f"cannot read JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise BaselineError(f"JSON input must be an object: {path}")
    return value


def _repo_path(raw: str) -> Path:
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise BaselineError(f"repository artifact path is not relative and bounded: {raw}")
    resolved = (ROOT / candidate).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise BaselineError(f"repository artifact escapes the repository: {raw}") from exc
    return resolved


def _configured_path(raw: str) -> Path:
    if raw.startswith("~/"):
        return Path(raw).expanduser().resolve()
    return _repo_path(raw)


def _safe_cli_path(path: Path, *, output: bool = False) -> Path:
    candidate = path if path.is_absolute() else ROOT / path
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise BaselineError(f"path must remain under the repository: {path}") from exc
    if output and candidate.exists() and candidate.is_symlink():
        raise BaselineError(f"output must not replace a symlink: {path}")
    return resolved


def _sha256_file(path: Path) -> str:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
            raise BaselineError(f"artifact must be a bounded regular file: {path}")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(64 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise BaselineError(f"cannot hash artifact: {path}") from exc
    return "sha256:" + digest.hexdigest()


def _sha256_json(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            contract = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BaselineError(f"cannot read baseline contract: {path}") from exc
    if contract.get("schema_version") != 1 or contract.get("name") != "SECURE_NATIVE_BASELINE":
        raise BaselineError("secure native baseline contract identity is invalid")
    if contract.get("issue") != 81 or contract.get("subscription_usage_measured") is not False:
        raise BaselineError("secure native baseline issue or usage-measurement contract is invalid")

    variants = contract.get("variants")
    if not isinstance(variants, dict) or tuple(variants) != ("A", "B", "C", "D"):
        raise BaselineError("variants must be ordered A, B, C, D")
    expected_variants = {
        "A": ("native_execution", "security_baseline"),
        "B": ("native_execution", "security_baseline", "canonical_state"),
        "C": ("native_execution", "security_baseline", "canonical_state", "continuity_helper"),
        "D": (
            "native_execution",
            "security_baseline",
            "canonical_state",
            "continuity_helper",
            "prompt_aware_recall",
        ),
    }
    for name, expected_layers in expected_variants.items():
        layers = variants.get(name)
        if not isinstance(layers, list) or not layers or not all(isinstance(item, str) and item for item in layers):
            raise BaselineError(f"variant {name} has invalid layers")
        if tuple(layers) != expected_layers:
            raise BaselineError(f"variant {name} layers must match the issue 81 experiment ladder")

    observations = contract.get("observations")
    benchmark = contract.get("benchmark")
    security = contract.get("security")
    scorecard_spec = contract.get("scorecard")
    comparison = contract.get("comparison")
    runtime_spec = contract.get("runtime")
    if not all(
        isinstance(section, dict)
        for section in (observations, benchmark, security, scorecard_spec, comparison, runtime_spec)
    ):
        raise BaselineError("contract sections are incomplete")
    for section, key in ((observations, "metric_ids"), (observations, "scenario_ids"), (benchmark, "scenario_ids"), (benchmark, "profiles")):
        values = section.get(key)
        if not isinstance(values, list) or not values or len(values) != len(set(values)):
            raise BaselineError(f"contract {key} values must be non-empty and unique")
    fixture_ids = security.get("fixture_ids")
    if not isinstance(fixture_ids, list) or len(fixture_ids) != security.get("expected_fixture_total") or len(fixture_ids) != len(set(fixture_ids)):
        raise BaselineError("contract security fixture ids must be exact and unique")
    blocked_ids = security.get("blocked_fixture_ids")
    allowed_ids = security.get("allowed_fixture_ids")
    if not isinstance(blocked_ids, list) or not isinstance(allowed_ids, list):
        raise BaselineError("contract security fixture outcomes are missing")
    if blocked_ids + allowed_ids != fixture_ids:
        raise BaselineError("contract security fixture outcomes do not match the stable identity order")
    if len(blocked_ids) != security.get("expected_blocked") or len(allowed_ids) != security.get("expected_allowed"):
        raise BaselineError("contract security fixture outcome counts drifted")
    if comparison.get("baseline_variant") != "A" or comparison.get("reference_required_for") != ["B", "C", "D"]:
        raise BaselineError("comparison reference policy is invalid")
    runtime_config_path = runtime_spec.get("config_path")
    if not isinstance(runtime_config_path, str) or not runtime_config_path.strip():
        raise BaselineError("runtime config path is invalid")
    _repo_path(runtime_config_path)
    scorecard = load_scorecard(_repo_path(scorecard_spec["path"]))
    if scorecard.get("id") != scorecard_spec["id"] or scorecard.get("version") != scorecard_spec["version"]:
        raise BaselineError("scorecard identity drifted")
    return contract


def _finite_nonnegative(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value)) and value >= 0


def _project_runtime_limits(contract: Mapping[str, Any]) -> dict[str, int]:
    path = _repo_path(contract["runtime"]["config_path"])
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
            raise BaselineError(f"runtime config must be a bounded regular file: {path}")
        with path.open("rb") as stream:
            project_config = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BaselineError(f"cannot read runtime config: {path}") from exc
    agents = project_config.get("agents")
    if not isinstance(agents, dict):
        raise BaselineError("project runtime config is missing agents")
    limits: dict[str, int] = {}
    for key in ("max_threads", "max_depth"):
        value = agents.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise BaselineError(f"project runtime config {key} must be a positive integer")
        limits[key] = value
    if limits["max_depth"] > 2:
        raise BaselineError("project runtime config max_depth must remain between 1 and 2")
    return limits


def validate_observations(contract: Mapping[str, Any], observations: Mapping[str, Any], variant: str) -> dict[str, Any]:
    spec = contract["observations"]
    if observations.get("schema_version") != spec["schema_version"]:
        raise BaselineError("observation schema_version is incompatible")
    if observations.get("variant") != variant:
        raise BaselineError("observation variant does not match the requested variant")
    for key in ("capture_id", "observed_at", "source"):
        if not observations.get(key):
            raise BaselineError(f"observations are missing {key}")
    if not isinstance(observations["source"], dict):
        raise BaselineError("observation source must be an object")
    if detect_secret_leak(json.dumps(observations, ensure_ascii=True, sort_keys=True)):
        raise BaselineError("observations contain sensitive material")

    statuses = set(spec["statuses"])
    metric_ids = list(spec["metric_ids"])
    metrics = observations.get("metrics")
    if not isinstance(metrics, dict) or set(metrics) != set(metric_ids):
        raise BaselineError("observations must provide every stable metric id exactly once")
    normalized_metrics: dict[str, dict[str, Any]] = {}
    for metric_id in metric_ids:
        item = metrics[metric_id]
        if not isinstance(item, dict) or item.get("status") not in statuses:
            raise BaselineError(f"metric {metric_id} has an invalid status")
        status = item["status"]
        value = item.get("value")
        if status == "measured":
            if not _finite_nonnegative(value) or not item.get("unit") or not item.get("evidence"):
                raise BaselineError(f"measured metric {metric_id} needs a finite value, unit, and evidence")
        elif value is not None or not item.get("reason"):
            raise BaselineError(f"unmeasured metric {metric_id} must use value=null and explain why")
        normalized_metrics[metric_id] = dict(item)

    scenario_ids = list(spec["scenario_ids"])
    scenarios = observations.get("scenarios")
    if not isinstance(scenarios, dict) or set(scenarios) != set(scenario_ids):
        raise BaselineError("observations must provide every stable scenario id exactly once")
    normalized_scenarios: dict[str, dict[str, Any]] = {}
    for scenario_id in scenario_ids:
        item = scenarios[scenario_id]
        if not isinstance(item, dict) or item.get("status") not in statuses:
            raise BaselineError(f"scenario {scenario_id} has an invalid status")
        status = item["status"]
        outcome = item.get("outcome")
        if status == "measured":
            if outcome not in {"PASS", "FAIL"} or not item.get("evidence"):
                raise BaselineError(f"measured scenario {scenario_id} needs PASS/FAIL and evidence")
        elif outcome is not None or not item.get("reason"):
            raise BaselineError(f"unmeasured scenario {scenario_id} must use outcome=null and explain why")
        normalized_scenarios[scenario_id] = dict(item)
    security_scenario = normalized_scenarios.get("security_suite")
    if not security_scenario or security_scenario.get("status") != "measured" or security_scenario.get("outcome") != "PASS":
        raise BaselineError("security_suite must be independently measured as PASS")

    runtime = observations.get("runtime")
    if not isinstance(runtime, dict):
        raise BaselineError("observations need bounded runtime metadata")
    for key in ("configured_model", "reasoning_effort"):
        if not isinstance(runtime.get(key), str) or not runtime[key]:
            raise BaselineError(f"runtime metadata is missing {key}")
    for key in ("max_threads", "max_depth"):
        if not isinstance(runtime.get(key), int) or isinstance(runtime[key], bool) or runtime[key] < 1:
            raise BaselineError(f"runtime metadata {key} must be a positive integer")
    if {key: runtime[key] for key in ("max_threads", "max_depth")} != _project_runtime_limits(contract):
        raise BaselineError("runtime concurrency does not match project config")

    return {
        "schema_version": observations["schema_version"],
        "capture_id": observations["capture_id"],
        "variant": variant,
        "observed_at": observations["observed_at"],
        "source": dict(observations["source"]),
        "runtime": dict(runtime),
        "metrics": normalized_metrics,
        "scenarios": normalized_scenarios,
        "limitations": list(observations.get("limitations") or []),
    }


def validate_benchmark(contract: Mapping[str, Any], benchmark: Mapping[str, Any]) -> dict[str, Any]:
    spec = contract["benchmark"]
    if benchmark.get("schema_version") != spec["schema_version"]:
        raise BaselineError("hook benchmark schema_version is incompatible")
    if benchmark.get("subscription_usage_measured") is not False:
        raise BaselineError("hook benchmark must not claim subscription usage measurement")
    if benchmark.get("scenario_names") != spec["scenario_ids"] or benchmark.get("profiles") != spec["profiles"]:
        raise BaselineError("hook benchmark scenario or profile identity drifted")
    required_numbers = (
        spec["primary_metric"],
        "total_p50_ms",
        "total_p95_ms",
        "total_stdout_chars",
        "estimated_context_units",
        "matched_handler_count",
        "executed_handler_count",
        "block_count",
    )
    for key in required_numbers:
        if not _finite_nonnegative(benchmark.get(key)):
            raise BaselineError(f"hook benchmark metric is missing or invalid: {key}")

    matrix = benchmark.get("scenario_matrix")
    if not isinstance(matrix, list):
        raise BaselineError("hook benchmark scenario_matrix is missing")
    expected = {(scenario, profile) for scenario in spec["scenario_ids"] for profile in spec["profiles"]}
    observed: set[tuple[str, str]] = set()
    attribution: list[dict[str, Any]] = []
    for item in matrix:
        if not isinstance(item, dict):
            raise BaselineError("hook benchmark contains a non-object scenario result")
        identity = (item.get("scenario"), item.get("profile"))
        if not all(isinstance(value, str) for value in identity) or identity in observed:
            raise BaselineError("hook benchmark contains an invalid or duplicate scenario identity")
        observed.add(identity)
        attribution.append(
            {
                "scenario": identity[0],
                "profile": identity[1],
                "event": item.get("event"),
                "runtime_p50_ms": item.get("runtime_p50_ms"),
                "runtime_p95_ms": item.get("runtime_p95_ms"),
                "output_bytes": item.get("output_bytes"),
                "matched_handler_count": item.get("matched_handler_count"),
                "executed_handler_count": item.get("executed_handler_count"),
                "block_count": item.get("block_count"),
            }
        )
    if observed != expected:
        raise BaselineError("hook benchmark matrix does not match the stable scenario/profile cross product")
    for item in attribution:
        if item["scenario"] == "red_safety" and item["block_count"] != 1:
            raise BaselineError("hook benchmark red_safety scenario was not blocked")
        if item["scenario"] == "small_read_only" and item["block_count"] != 0:
            raise BaselineError("hook benchmark small_read_only scenario was unexpectedly blocked")

    return {
        "schema_version": benchmark["schema_version"],
        "primary_metric": spec["primary_metric"],
        "direction": spec["direction"],
        "hook_cost_score": benchmark[spec["primary_metric"]],
        "total_p50_ms": benchmark["total_p50_ms"],
        "total_p95_ms": benchmark["total_p95_ms"],
        "output_bytes": benchmark["total_stdout_chars"],
        "estimated_context_units": benchmark["estimated_context_units"],
        "matched_handler_count": benchmark["matched_handler_count"],
        "executed_handler_count": benchmark["executed_handler_count"],
        "block_count": benchmark["block_count"],
        "iterations": benchmark.get("iterations"),
        "warmup_iterations": benchmark.get("warmup_iterations"),
        "subscription_usage_measured": False,
        "scenario_attribution": attribution,
        "limitations": list(benchmark.get("limitations") or []),
    }


def _run_json(script: Path, *arguments: str, timeout: int = 90) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
        env=env,
    )
    if result.returncode != 0:
        raise BaselineError(f"validation command failed: {script.relative_to(ROOT)}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise BaselineError(f"validation command did not emit JSON: {script.relative_to(ROOT)}") from exc
    if not isinstance(value, dict):
        raise BaselineError(f"validation command emitted a non-object: {script.relative_to(ROOT)}")
    return value


def collect_artifact_hashes(contract: Mapping[str, Any]) -> dict[str, str]:
    security = contract["security"]
    scorecard = contract["scorecard"]
    benchmark = contract["benchmark"]
    runtime = contract["runtime"]
    paths = {
        "capture_contract": DEFAULT_CONTRACT,
        "project_runtime_config": _repo_path(runtime["config_path"]),
        "security_contract": _repo_path(security["contract_path"]),
        "security_runner": _repo_path(security["runner_path"]),
        "project_dispatcher": _repo_path(security["dispatcher_path"]),
        "project_hook_config": _repo_path(security["project_hook_config_path"]),
        "global_dispatcher": _configured_path(security["global_dispatcher_path"]),
        "global_hook_config": _configured_path(security["global_hook_config_path"]),
        "effective_graph_runner": _repo_path(security["effective_graph_runner_path"]),
        "hook_benchmark_runner": _repo_path(benchmark["runner_path"]),
        "scorecard": _repo_path(scorecard["path"]),
    }
    hashes = {name: _sha256_file(path) for name, path in paths.items()}
    if hashes["project_dispatcher"] != hashes["global_dispatcher"]:
        raise BaselineError("project and global security dispatcher hashes differ")
    return hashes


def attest_security(
    contract: Mapping[str, Any],
    security_report: Mapping[str, Any],
    graph_report: Mapping[str, Any],
    artifact_hashes: Mapping[str, str],
) -> dict[str, Any]:
    spec = contract["security"]
    if security_report.get("name") != spec["expected_name"] or security_report.get("version") != spec["expected_version"]:
        raise BaselineError("SECURITY_BASELINE identity drifted")
    if security_report.get("passed") is not True:
        raise BaselineError("SECURITY_BASELINE did not pass")
    results = security_report.get("results")
    if not isinstance(results, list) or len(results) != spec["expected_fixture_total"]:
        raise BaselineError("SECURITY_BASELINE fixture count drifted")
    fixture_ids = [item.get("name") for item in results if isinstance(item, dict)]
    if fixture_ids != spec["fixture_ids"]:
        raise BaselineError("SECURITY_BASELINE fixture identities drifted")
    if any(not isinstance(item, dict) or item.get("passed") is not True for item in results):
        raise BaselineError("one or more SECURITY_BASELINE fixtures failed")
    expected_outcomes = {
        **{fixture_id: "blocked" for fixture_id in spec["blocked_fixture_ids"]},
        **{fixture_id: "allowed" for fixture_id in spec["allowed_fixture_ids"]},
    }
    if any(item.get("expected") != expected_outcomes[item["name"]] or item.get("observed") != expected_outcomes[item["name"]] for item in results):
        raise BaselineError("SECURITY_BASELINE fixture outcomes drifted")
    blocked = sum(item.get("expected") == "blocked" and item.get("observed") == "blocked" for item in results)
    allowed = sum(item.get("expected") == "allowed" and item.get("observed") == "allowed" for item in results)
    if blocked != spec["expected_blocked"] or allowed != spec["expected_allowed"]:
        raise BaselineError("SECURITY_BASELINE blocked/allowed balance drifted")

    if graph_report.get("status") != spec["expected_graph_status"] or graph_report.get("profile") != spec["expected_profile"]:
        raise BaselineError("effective hook graph status or profile drifted")
    domains = graph_report.get("domains")
    if not isinstance(domains, list):
        raise BaselineError("effective hook graph domains are missing")
    domain_pairs = [
        (item.get("domain"), item.get("status"))
        for item in domains
        if isinstance(item, dict) and isinstance(item.get("domain"), str)
    ]
    domain_names = [name for name, _status in domain_pairs]
    if len(domain_pairs) != len(domains) or len(domain_names) != len(set(domain_names)):
        raise BaselineError("effective hook graph domains contain invalid or duplicate identities")
    observed_domains = dict(domain_pairs)
    if observed_domains != spec["expected_domain_status"]:
        raise BaselineError("effective hook graph domain ownership drifted")
    if graph_report.get("legacy_wrapper_registered") is not False:
        raise BaselineError("legacy hook wrapper is still registered")

    try:
        security_artifact_hashes = {key: artifact_hashes[key] for key in SECURITY_ARTIFACT_KEYS}
    except KeyError as exc:
        raise BaselineError(f"security artifact hash is missing: {exc.args[0]}") from exc
    summary = {
        "name": security_report["name"],
        "version": security_report["version"],
        "status": "PASS",
        "fixture_total": len(results),
        "dangerous_blocked": blocked,
        "innocuous_allowed": allowed,
        "fixture_results": [
            {
                "id": item["name"],
                "expected": item["expected"],
                "observed": item["observed"],
                "passed": item["passed"],
            }
            for item in results
        ],
        "effective_graph": {
            "status": graph_report["status"],
            "profile": graph_report["profile"],
            "domains": observed_domains,
            "legacy_wrapper_registered": graph_report["legacy_wrapper_registered"],
        },
        "artifact_hashes": security_artifact_hashes,
    }
    summary["manifest_hash"] = _sha256_json(summary)
    return summary


def build_report(
    contract: Mapping[str, Any],
    observations: Mapping[str, Any],
    benchmark: Mapping[str, Any],
    security: Mapping[str, Any],
    *,
    artifact_hashes: Mapping[str, str],
    benchmark_report_hash: str,
) -> dict[str, Any]:
    scenario_counts = {status: 0 for status in contract["observations"]["statuses"]}
    for item in observations["scenarios"].values():
        scenario_counts[item["status"]] += 1
    metric_counts = {status: 0 for status in contract["observations"]["statuses"]}
    for item in observations["metrics"].values():
        metric_counts[item["status"]] += 1
    coverage_status = "FULL" if scenario_counts["not_measured"] == 0 and metric_counts["not_measured"] == 0 else "PARTIAL"
    comparison_contract = {
        "capture_contract_hash": artifact_hashes["capture_contract"],
        "project_runtime_config_hash": artifact_hashes["project_runtime_config"],
        "hook_benchmark_runner_hash": artifact_hashes["hook_benchmark_runner"],
        "scorecard_hash": artifact_hashes["scorecard"],
        "security_manifest_hash": security["manifest_hash"],
        "hook_benchmark_report_hash": benchmark_report_hash,
        "hook_benchmark_schema_version": benchmark["schema_version"],
        "native_scenario_ids": contract["observations"]["scenario_ids"],
        "native_metric_ids": contract["observations"]["metric_ids"],
        "hook_scenario_ids": contract["benchmark"]["scenario_ids"],
        "hook_profiles": contract["benchmark"]["profiles"],
    }
    comparison_contract["identity_hash"] = _sha256_json(comparison_contract)
    return {
        "schema_version": contract["schema_version"],
        "schema_name": contract["report_schema"],
        "issue": contract["issue"],
        "capture_id": observations["capture_id"],
        "observed_at": observations["observed_at"],
        "variant": observations["variant"],
        "variant_layers": contract["variants"][observations["variant"]],
        "status": "PASS",
        "coverage_status": coverage_status,
        "coverage": {"metrics": metric_counts, "scenarios": scenario_counts},
        "source": observations["source"],
        "runtime": observations["runtime"],
        "native_metrics": observations["metrics"],
        "native_scenarios": observations["scenarios"],
        "security_baseline": dict(security),
        "security_overhead": dict(benchmark),
        "comparison_contract": comparison_contract,
        "scorecard": dict(contract["scorecard"]),
        "subscription_usage_measured": False,
        "limitations": list(observations["limitations"]),
    }


def validate_reference(contract: Mapping[str, Any], report: Mapping[str, Any], reference: Mapping[str, Any]) -> dict[str, Any]:
    comparison = contract["comparison"]
    if (
        reference.get("schema_name") != contract["report_schema"]
        or reference.get("issue") != contract["issue"]
        or reference.get("variant") != comparison["baseline_variant"]
        or reference.get("status") != "PASS"
    ):
        raise BaselineError("comparison reference is not the variant A secure native baseline")
    capture_id = reference.get("capture_id")
    if not isinstance(capture_id, str) or not capture_id.strip():
        raise BaselineError("comparison reference capture id is invalid")
    reference_contract = reference.get("comparison_contract")
    report_contract = report.get("comparison_contract")
    if not isinstance(reference_contract, dict) or not isinstance(report_contract, dict):
        raise BaselineError("comparison reference contract is missing")
    stable_fields = (
        "capture_contract_hash",
        "project_runtime_config_hash",
        "hook_benchmark_runner_hash",
        "scorecard_hash",
        "security_manifest_hash",
        "hook_benchmark_schema_version",
        "native_scenario_ids",
        "native_metric_ids",
        "hook_scenario_ids",
        "hook_profiles",
    )
    drifted = [field for field in stable_fields if reference_contract.get(field) != report_contract.get(field)]
    if drifted:
        raise BaselineError(f"comparison reference drifted: {', '.join(drifted)}")
    reference_identity = reference_contract.get("identity_hash")
    identity_payload = {key: value for key, value in reference_contract.items() if key != "identity_hash"}
    if reference_identity != _sha256_json(identity_payload):
        raise BaselineError("comparison reference identity hash is invalid")
    return {
        "capture_id": capture_id,
        "variant": reference.get("variant"),
        "security_manifest_hash": reference_contract["security_manifest_hash"],
        "capture_contract_hash": reference_contract["capture_contract_hash"],
        "identity_hash": reference_identity,
        "report_hash": _sha256_json(reference),
    }


def _display_observation(item: Mapping[str, Any], value_key: str) -> str:
    if item.get("status") == "measured":
        value = item.get(value_key)
        unit = item.get("unit") if value_key == "value" else ""
        return f"{value} {unit}".strip()
    return f"unknown ({item.get('reason')})" if item.get("status") == "not_measured" else f"n/a ({item.get('reason')})"


def markdown_report(report: Mapping[str, Any]) -> str:
    security = report["security_baseline"]
    overhead = report["security_overhead"]
    lines = [
        "# Issue #81 secure native baseline",
        "",
        f"- Capture: `{report['capture_id']}`",
        f"- Variant: `{report['variant']}` (`{' + '.join(report['variant_layers'])}`)",
        f"- Result: `{report['status']}`; coverage: `{report['coverage_status']}`",
        f"- SECURITY_BASELINE: `{security['status']}` ({security['dangerous_blocked']} dangerous blocked, {security['innocuous_allowed']} innocuous allowed)",
        f"- Security manifest: `{security['manifest_hash']}`",
        f"- Comparison identity: `{report['comparison_contract']['identity_hash']}`",
        "",
        "## Native metrics",
        "",
        "| Metric | Status | Observation | Evidence or reason |",
        "|---|---|---:|---|",
    ]
    for metric_id, item in report["native_metrics"].items():
        evidence = item.get("evidence") or item.get("reason")
        lines.append(f"| `{metric_id}` | {item['status']} | {_display_observation(item, 'value')} | {evidence} |")
    lines.extend(
        [
            "",
            "## Native scenarios",
            "",
            "| Scenario | Status | Outcome | Evidence or reason |",
            "|---|---|---|---|",
        ]
    )
    for scenario_id, item in report["native_scenarios"].items():
        evidence = item.get("evidence") or item.get("reason")
        lines.append(f"| `{scenario_id}` | {item['status']} | {_display_observation(item, 'outcome')} | {evidence} |")
    lines.extend(
        [
            "",
            "## Security overhead (separate attribution)",
            "",
            f"- Primary metric: `{overhead['primary_metric']}={overhead['hook_cost_score']}` ({overhead['direction']} is better)",
            f"- Aggregate p50/p95: `{overhead['total_p50_ms']} ms` / `{overhead['total_p95_ms']} ms`",
            f"- Hook output: `{overhead['output_bytes']} bytes` (`{overhead['estimated_context_units']}` estimated context units)",
            f"- Executed handlers: `{overhead['executed_handler_count']}`; blocks: `{overhead['block_count']}`",
            "- Provider subscription tokens or credits were not measured.",
            "",
            "## Limitations",
            "",
            *[f"- {item}" for item in report.get("limitations", [])],
        ]
    )
    return "\n".join(lines) + "\n"


def capture(variant: str, observations_path: Path, benchmark_path: Path, reference_path: Path | None = None) -> dict[str, Any]:
    contract = load_contract()
    if variant not in contract["variants"]:
        raise BaselineError(f"unknown variant: {variant}")
    reference_required = variant in contract["comparison"]["reference_required_for"]
    if reference_required and reference_path is None:
        raise BaselineError(f"variant {variant} requires a variant A comparison reference")
    observations = validate_observations(contract, _load_json(observations_path), variant)
    benchmark_raw = _load_json(benchmark_path)
    benchmark = validate_benchmark(contract, benchmark_raw)
    hashes = collect_artifact_hashes(contract)
    security_spec = contract["security"]
    security_report = _run_json(_repo_path(security_spec["runner_path"]))
    graph_report = _run_json(_repo_path(security_spec["effective_graph_runner_path"]), "--json")
    security = attest_security(contract, security_report, graph_report, hashes)
    report = build_report(
        contract,
        observations,
        benchmark,
        security,
        artifact_hashes=hashes,
        benchmark_report_hash=_sha256_file(benchmark_path),
    )
    if reference_required:
        report["comparison_reference"] = validate_reference(contract, report, _load_json(reference_path))
    elif reference_path is not None:
        report["comparison_reference"] = validate_reference(contract, report, _load_json(reference_path))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", required=True, choices=("A", "B", "C", "D"))
    parser.add_argument("--observations", required=True, type=Path)
    parser.add_argument("--hook-benchmark", required=True, type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--json-out", required=True, type=Path)
    parser.add_argument("--markdown-out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        observations_path = _safe_cli_path(args.observations)
        benchmark_path = _safe_cli_path(args.hook_benchmark)
        reference_path = _safe_cli_path(args.reference) if args.reference else None
        json_out = _safe_cli_path(args.json_out, output=True)
        markdown_out = _safe_cli_path(args.markdown_out, output=True)
        report = capture(args.variant, observations_path, benchmark_path, reference_path)
        rendered = markdown_report(report)
        if detect_secret_leak(json.dumps(report, ensure_ascii=True, sort_keys=True) + rendered):
            raise BaselineError("generated baseline report contains sensitive material")
        write_json(json_out, report)
        markdown_out.parent.mkdir(parents=True, exist_ok=True)
        markdown_out.write_text(rendered, encoding="utf-8")
    except (BaselineError, subprocess.TimeoutExpired) as exc:
        print(f"SECURE_NATIVE_BASELINE_FAIL {exc}", file=sys.stderr)
        return 1
    print(
        "SECURE_NATIVE_BASELINE_PASS "
        f"variant={report['variant']} capture={report['capture_id']} "
        f"security_manifest={report['security_baseline']['manifest_hash']}"
    )
    print(f"METRIC hook_cost_score={report['security_overhead']['hook_cost_score']}")
    print(f"METRIC hook_total_p50_ms={report['security_overhead']['total_p50_ms']}")
    print(f"METRIC hook_output_context_units={report['security_overhead']['estimated_context_units']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
