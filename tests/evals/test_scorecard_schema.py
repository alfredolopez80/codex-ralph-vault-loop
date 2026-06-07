from __future__ import annotations

from pathlib import Path

from scripts.evals._eval_common import HARD_GATES, RASS_WEIGHTS, load_scorecard, load_yaml_mapping


ROOT = Path(__file__).resolve().parents[2]
SCORECARDS = ROOT / "config" / "scorecards"


def test_all_scorecards_parse_and_match_rass_weights() -> None:
    for path in SCORECARDS.glob("*.yaml"):
        data = load_scorecard(path)
        assert set(data["weights"]) == set(RASS_WEIGHTS)
        assert abs(sum(float(value) for value in data["weights"].values()) - 1.0) < 1e-9
        if path.name != "memory_retrieval_v2.yaml":
            assert data["weights"] == RASS_WEIGHTS
        assert set(data["hard_gates"]) >= HARD_GATES
        assert set(data["metrics"]) == set(RASS_WEIGHTS)


def test_load_yaml_mapping_returns_mapping() -> None:
    data = load_yaml_mapping(SCORECARDS / "cost_router_v1.yaml")
    assert isinstance(data, dict)
    assert data["id"] == "cost_router_v1"
