from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts" / "evals"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import subagent_routing_eval as evaluation


def test_fixture_eval_is_deterministic_and_routes_only_high_value_work() -> None:
    report = evaluation.evaluate(iterations=3)

    assert report["schema_version"] == 1
    assert report["max_threads"] == 2
    assert report["max_depth"] == 1
    assert report["first_pass_success_rate"] == 1.0
    assert [case["route"] for case in report["cases"]] == [
        "none",
        "none",
        "sol-advisor",
        "sol-advisor",
    ]
    assert report["subscription_usage_measured"] is False


def test_eval_report_contains_no_fixture_prompt_or_raw_content(tmp_path: Path) -> None:
    report = evaluation.evaluate(iterations=1)
    output = json.dumps(report, sort_keys=True)
    assert "Implement the bounded" not in output
    assert "fixture-failure-a" not in output

    markdown = evaluation.markdown(report)
    assert "small_bugfix" in markdown
    assert "failing_tests" in markdown
