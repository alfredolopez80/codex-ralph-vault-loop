from __future__ import annotations

from pathlib import Path

import yaml

from scripts.evals._eval_common import HARD_GATES, RASS_WEIGHTS, load_scorecard


ROOT = Path(__file__).resolve().parents[2]
SCORECARDS = ROOT / "config" / "scorecards"


def test_all_scorecards_parse_and_match_rass_weights() -> None:
    for path in SCORECARDS.glob("*.yaml"):
        data = load_scorecard(path)
        assert data["weights"] == RASS_WEIGHTS
        assert set(data["hard_gates"]) >= HARD_GATES
        assert set(data["metrics"]) == set(RASS_WEIGHTS)


def test_yaml_safe_load_returns_mapping() -> None:
    data = yaml.safe_load((SCORECARDS / "cost_router_v1.yaml").read_text())
    assert isinstance(data, dict)
    assert data["id"] == "cost_router_v1"
