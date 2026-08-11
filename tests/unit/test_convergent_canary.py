from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "evals" / "convergent_execution_canary.py"
MANIFEST = ROOT / "docs" / "reports" / "ralph-convergent-execution-v4" / "corpus-manifest.json"


def load_canary():
    spec = importlib.util.spec_from_file_location("convergent_execution_canary_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_canary_executes_candidate_predicates_and_explains_divergence() -> None:
    canary = load_canary()
    report = canary.evaluate(json.loads(MANIFEST.read_text(encoding="utf-8")))
    assert report["pass"] is True
    assert report["result_scope"] == "STRUCTURAL_ONLY"
    assert report["paired_corpus_execution"] == "UNKNOWN"
    assert len(report["scenario_results"]) == 24
    assert any(item["different"] for item in report["scenario_results"])
    assert all("candidate_observation" in item for item in report["scenario_results"])
    assert all(item["divergence_explained"] for item in report["scenario_results"])
    assert report["hard_gates"]["declared_risk_classes"] is True
    assert all(item["risk_match"] is True for item in report["scenario_results"])


def test_canary_fails_closed_when_a_required_candidate_predicate_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    canary = load_canary()

    class BrokenFastPath:
        eligible = False
        reason = "broken-fixture"

    monkeypatch.setattr(canary, "successful_read_fast_path", lambda _payload: BrokenFastPath())
    with pytest.raises(ValueError, match="successful-read fixture"):
        canary.evaluate(json.loads(MANIFEST.read_text(encoding="utf-8")))


def test_canary_rejects_a_duplicate_or_relabelled_corpus() -> None:
    canary = load_canary()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["scenarios"][-1] = dict(manifest["scenarios"][0])
    with pytest.raises(ValueError, match="approved paired corpus|digest"):
        canary.evaluate(manifest)
