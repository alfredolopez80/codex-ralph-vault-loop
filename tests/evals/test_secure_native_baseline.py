from __future__ import annotations

from pathlib import Path

import pytest

from scripts.evals import secure_native_baseline as baseline
from scripts.evals.secure_native_baseline import (
    BaselineError,
    attest_security,
    build_report,
    capture,
    load_contract,
    markdown_report,
    validate_benchmark,
    validate_observations,
    validate_reference,
)


def _observations(contract: dict, variant: str = "A") -> dict:
    metrics = {
        metric_id: {"status": "measured", "value": index + 1, "unit": "count", "evidence": "unit fixture"}
        for index, metric_id in enumerate(contract["observations"]["metric_ids"])
    }
    metrics["time_to_first_useful_action_ms"] = {
        "status": "not_measured",
        "value": None,
        "unit": "ms",
        "reason": "source metadata does not expose this timestamp",
    }
    return {
        "schema_version": 1,
        "capture_id": "unit-a",
        "variant": variant,
        "observed_at": "2026-08-22T10:00:00Z",
        "source": {"kind": "unit_fixture", "reference": "local"},
        "runtime": {"configured_model": "gpt-5.6-luna", "reasoning_effort": "max", "max_threads": 8, "max_depth": 1},
        "metrics": metrics,
        "scenarios": {
            scenario_id: {"status": "measured", "outcome": "PASS", "evidence": "unit fixture"}
            for scenario_id in contract["observations"]["scenario_ids"]
        },
    }


def _benchmark(contract: dict) -> dict:
    matrix = [
        {
            "scenario": scenario,
            "profile": profile,
            "event": "PreToolUse",
            "runtime_p50_ms": 1.0,
            "runtime_p95_ms": 2.0,
            "output_bytes": 0,
            "matched_handler_count": 1,
            "executed_handler_count": 1,
            "block_count": int(scenario == "red_safety"),
        }
        for scenario in contract["benchmark"]["scenario_ids"]
        for profile in contract["benchmark"]["profiles"]
    ]
    return {
        "schema_version": contract["benchmark"]["schema_version"],
        "subscription_usage_measured": False,
        "scenario_names": contract["benchmark"]["scenario_ids"],
        "profiles": contract["benchmark"]["profiles"],
        "scenario_matrix": matrix,
        "hook_cost_score": 42.0,
        "total_p50_ms": 30.0,
        "total_p95_ms": 60.0,
        "total_stdout_chars": 12,
        "estimated_context_units": 3,
        "matched_handler_count": 30,
        "executed_handler_count": 30,
        "block_count": 3,
    }


def _security_report(contract: dict) -> dict:
    outcomes = [
        (fixture_id, outcome)
        for outcome, fixture_ids in (("blocked", contract["security"]["blocked_fixture_ids"]), ("allowed", contract["security"]["allowed_fixture_ids"]))
        for fixture_id in fixture_ids
    ]
    return {
        "name": "SECURITY_BASELINE",
        "version": 2,
        "passed": True,
        "results": [{"name": name, "expected": outcome, "observed": outcome, "passed": True} for name, outcome in outcomes],
    }


def _graph_report(contract: dict) -> dict:
    return {
        "status": "PASS",
        "profile": "security-only",
        "legacy_wrapper_registered": False,
        "domains": [{"domain": domain, "status": status} for domain, status in contract["security"]["expected_domain_status"].items()],
    }


def _artifact_hashes() -> dict[str, str]:
    return {
        "capture_contract": "sha256:capture",
        "project_runtime_config": "sha256:runtime-config",
        "security_contract": "sha256:security-contract",
        "security_runner": "sha256:security-runner",
        "project_dispatcher": "sha256:dispatcher",
        "project_hook_config": "sha256:project-hooks",
        "global_dispatcher": "sha256:dispatcher",
        "global_hook_config": "sha256:global-hooks",
        "effective_graph_runner": "sha256:graph-runner",
        "hook_benchmark_runner": "sha256:benchmark-runner",
        "scorecard": "sha256:scorecard",
    }


def _report(contract: dict, variant: str) -> dict:
    return build_report(
        contract,
        validate_observations(contract, _observations(contract, variant), variant),
        validate_benchmark(contract, _benchmark(contract)),
        attest_security(contract, _security_report(contract), _graph_report(contract), _artifact_hashes()),
        artifact_hashes=_artifact_hashes(),
        benchmark_report_hash="sha256:benchmark",
    )


def test_contract_keeps_the_exact_ladder_and_security_fixture_partition() -> None:
    contract = load_contract()
    assert contract["variants"] == {
        "A": ["native_execution", "security_baseline"],
        "B": ["native_execution", "security_baseline", "canonical_state"],
        "C": ["native_execution", "security_baseline", "canonical_state", "continuity_helper"],
        "D": ["native_execution", "security_baseline", "canonical_state", "continuity_helper", "prompt_aware_recall"],
    }
    security = contract["security"]
    assert security["expected_fixture_total"] == len(security["fixture_ids"]) == 15
    assert security["expected_blocked"] == len(security["blocked_fixture_ids"]) == 7
    assert security["expected_allowed"] == len(security["allowed_fixture_ids"]) == 8
    assert security["blocked_fixture_ids"] + security["allowed_fixture_ids"] == security["fixture_ids"]


def test_contract_rejects_ladder_drift(tmp_path: Path) -> None:
    source = Path("config/secure-native-baseline.toml").read_text(encoding="utf-8")
    path = tmp_path / "contract.toml"
    path.write_text(source.replace('A = ["native_execution", "security_baseline"]', 'A = ["security_baseline"]', 1), encoding="utf-8")

    with pytest.raises(BaselineError, match="variant A layers must match"):
        load_contract(path)


def test_unknown_native_metrics_remain_null_and_are_not_rendered_as_zero() -> None:
    report = _report(load_contract(), "A")
    assert report["native_metrics"]["time_to_first_useful_action_ms"]["value"] is None
    assert report["coverage_status"] == "PARTIAL"
    assert "unknown (source metadata does not expose this timestamp)" in markdown_report(report)


@pytest.mark.parametrize(
    ("mutation", "error"),
    (
        (lambda report: report["results"].pop(), "fixture count drifted"),
        (lambda report: report["results"].__setitem__(0, {**report["results"][0], "observed": "allowed"}), "fixture outcomes drifted"),
        (lambda report: report["results"].__setitem__(0, {**report["results"][0], "name": "replacement"}), "fixture identities drifted"),
    ),
)
def test_security_attestation_rejects_fixture_count_outcome_and_identity_drift(mutation: object, error: str) -> None:
    contract = load_contract()
    drifted = _security_report(contract)
    mutation(drifted)  # type: ignore[operator]
    with pytest.raises(BaselineError, match=error):
        attest_security(contract, drifted, _graph_report(contract), _artifact_hashes())


@pytest.mark.parametrize(
    ("mutation", "error"),
    (
        (lambda report: report.__setitem__("status", "FAIL"), "status or profile drifted"),
        (lambda report: report.__setitem__("profile", "default"), "status or profile drifted"),
    ),
)
def test_security_attestation_rejects_graph_status_and_profile_drift(mutation: object, error: str) -> None:
    contract = load_contract()
    graph = _graph_report(contract)
    mutation(graph)  # type: ignore[operator]
    with pytest.raises(BaselineError, match=error):
        attest_security(contract, _security_report(contract), graph, _artifact_hashes())


def test_security_attestation_rejects_duplicate_or_missing_graph_domains() -> None:
    contract = load_contract()
    for domains in (
        [{"domain": "pre_tool_safety", "status": "PASS"}] * 2,
        _graph_report(contract)["domains"][:-1],
    ):
        graph = _graph_report(contract)
        graph["domains"] = domains
        with pytest.raises(BaselineError, match="domains contain invalid or duplicate identities|domain ownership drifted"):
            attest_security(contract, _security_report(contract), graph, _artifact_hashes())


def test_security_attestation_rejects_legacy_graph_wrapper() -> None:
    contract = load_contract()
    graph = _graph_report(contract)
    graph["legacy_wrapper_registered"] = True
    with pytest.raises(BaselineError, match="legacy hook wrapper"):
        attest_security(contract, _security_report(contract), graph, _artifact_hashes())


@pytest.mark.parametrize(
    ("mutation", "error"),
    (
        (lambda report: report.__setitem__("profiles", ["luna"]), "scenario or profile identity drifted"),
        (lambda report: report.__setitem__("scenario_names", ["small_read_only"]), "scenario or profile identity drifted"),
    ),
)
def test_benchmark_rejects_profile_and_scenario_identity_drift(mutation: object, error: str) -> None:
    contract = load_contract()
    benchmark = _benchmark(contract)
    mutation(benchmark)  # type: ignore[operator]
    with pytest.raises(BaselineError, match=error):
        validate_benchmark(contract, benchmark)


@pytest.mark.parametrize("remove", (False, True))
def test_benchmark_rejects_duplicate_or_missing_cross_product_rows(remove: bool) -> None:
    contract = load_contract()
    benchmark = _benchmark(contract)
    if remove:
        benchmark["scenario_matrix"].pop()
    else:
        benchmark["scenario_matrix"].append(dict(benchmark["scenario_matrix"][0]))
    with pytest.raises(BaselineError, match="duplicate scenario identity|does not match the stable"):
        validate_benchmark(contract, benchmark)


def test_benchmark_requires_red_safety_to_block() -> None:
    contract = load_contract()
    benchmark = _benchmark(contract)
    next(row for row in benchmark["scenario_matrix"] if row["scenario"] == "red_safety")["block_count"] = 0
    with pytest.raises(BaselineError, match="red_safety scenario was not blocked"):
        validate_benchmark(contract, benchmark)


def test_reference_rejects_a_non_a_baseline() -> None:
    contract = load_contract()
    candidate, reference = _report(contract, "B"), _report(contract, "A")
    reference["variant"] = "B"
    with pytest.raises(BaselineError, match="not the variant A"):
        validate_reference(contract, candidate, reference)


def test_reference_rejects_stable_field_drift() -> None:
    contract = load_contract()
    candidate, reference = _report(contract, "B"), _report(contract, "A")
    reference["comparison_contract"]["scorecard_hash"] = "sha256:drifted"
    with pytest.raises(BaselineError, match="comparison reference drifted: scorecard_hash"):
        validate_reference(contract, candidate, reference)


def test_reference_rejects_an_invalid_identity_hash() -> None:
    contract = load_contract()
    candidate, reference = _report(contract, "B"), _report(contract, "A")
    reference["comparison_contract"]["identity_hash"] = "sha256:tampered"
    with pytest.raises(BaselineError, match="reference identity hash is invalid"):
        validate_reference(contract, candidate, reference)


def test_later_variants_require_a_variant_a_reference() -> None:
    missing = Path("does-not-exist.json")
    for variant in ("B", "C", "D"):
        with pytest.raises(BaselineError, match=f"variant {variant} requires a variant A comparison reference"):
            capture(variant, missing, missing)


@pytest.mark.parametrize(
    ("section", "item_id", "field", "error"),
    (
        ("metrics", "time_to_first_useful_action_ms", "value", "unmeasured metric"),
        ("scenarios", "trivial_file_edit", "outcome", "unmeasured scenario"),
    ),
)
def test_not_measured_observations_require_null_values(
    section: str, item_id: str, field: str, error: str
) -> None:
    contract = load_contract()
    observations = _observations(contract)
    observations[section][item_id] = {"status": "not_measured", field: 1, "reason": "unavailable"}
    with pytest.raises(BaselineError, match=error):
        validate_observations(contract, observations, "A")


def test_observations_must_match_project_runtime_concurrency() -> None:
    contract = load_contract()
    observations = _observations(contract)
    observations["runtime"]["max_threads"] = 7

    with pytest.raises(BaselineError, match="runtime concurrency does not match project config"):
        validate_observations(contract, observations, "A")


def test_report_keeps_native_metrics_and_security_overhead_separate() -> None:
    report = _report(load_contract(), "A")
    assert "hook_cost_score" not in report["native_metrics"]
    assert report["security_overhead"]["hook_cost_score"] == 42.0
    assert "Security overhead (separate attribution)" in markdown_report(report)


def test_artifact_collection_rejects_project_global_dispatcher_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    contract = load_contract()

    def fake_hash(path: Path) -> str:
        return "sha256:global" if path.is_relative_to(Path.home() / ".codex") else "sha256:project"

    monkeypatch.setattr(baseline, "_sha256_file", fake_hash)
    with pytest.raises(BaselineError, match="project and global security dispatcher hashes differ"):
        baseline.collect_artifact_hashes(contract)
