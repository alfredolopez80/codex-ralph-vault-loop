from __future__ import annotations

from scripts.evals._eval_common import clamp_score, normalize_metrics, score_run


def test_clamp_score_accepts_boolean_percent_and_ratio() -> None:
    assert clamp_score(True) == 1.0
    assert clamp_score(False) == 0.0
    assert clamp_score(80) == 0.8
    assert clamp_score(0.25) == 0.25
    assert clamp_score(-1) == 0.0
    assert clamp_score(200) == 1.0


def test_normalize_metrics_returns_zero_to_one_values() -> None:
    values = normalize_metrics({"a": 100, "b": 0.5, "c": False})
    assert values == {"a": 1.0, "b": 0.5, "c": 0.0}


def test_score_run_zeroes_score_when_hard_gate_fails() -> None:
    scorecard = {
        "id": "unit",
        "weights": {
            "effectiveness": 0.35,
            "efficiency": 0.20,
            "reliability_safety": 0.20,
            "memory_research_quality": 0.15,
            "maintainability_simplicity": 0.10,
        },
        "metrics": {
            "effectiveness": ["a"],
            "efficiency": ["b"],
            "reliability_safety": ["c"],
            "memory_research_quality": ["d"],
            "maintainability_simplicity": ["e"],
        },
    }
    metrics = {"a": 1, "b": 1, "c": 1, "d": 1, "e": 1}
    gates = {
        "tests_pass": True,
        "no_secret_leak": False,
        "eval_harness_unchanged": True,
        "no_scope_violation": True,
        "no_eval_gaming": True,
    }
    result = score_run(scorecard, metrics, gates)
    assert result["score"] == 0.0
    assert result["hard_gates"]["failed"] == ["no_secret_leak"]
