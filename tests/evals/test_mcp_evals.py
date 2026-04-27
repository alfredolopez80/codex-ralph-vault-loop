from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "scripts" / "evals" / "research_eval.py"
VISION = ROOT / "scripts" / "evals" / "vision_eval.py"
CODING = ROOT / "scripts" / "evals" / "coding_model_eval.py"
RESEARCH_FIXTURE = ROOT / "tests" / "evals" / "fixtures" / "research_citation" / "manifest.json"


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def load_output(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_research_eval_mock_scores_citations_and_cost(tmp_path: Path) -> None:
    output = tmp_path / "research.json"
    result = run_script(str(RESEARCH), "--mode", "mock", "--output", str(output))

    assert result.returncode == 0, result.stderr
    report = load_output(output)
    assert report["status"] == "completed"
    assert report["metrics"]["source_quality"] == 1.0
    assert report["metrics"]["faithfulness"] == 1.0
    assert report["metrics"]["recency_fit"] == 1.0
    assert report["red_blocked"] is True
    assert report["score"] == 1.0


def test_vision_eval_mock_blocks_generation_use(tmp_path: Path) -> None:
    output = tmp_path / "vision.json"
    result = run_script(str(VISION), "--mode", "mock", "--output", str(output))

    assert result.returncode == 0, result.stderr
    report = load_output(output)
    assert report["generation_allowed"] is False
    assert report["metrics"]["ocr_correctness"] == 1.0
    assert report["metrics"]["diagram_understanding"] == 1.0
    assert report["metrics"]["ui_diff_correctness"] == 1.0
    assert report["metrics"]["no_generation_usage"] == 1.0
    assert report["metrics"]["safety"] == 1.0


def test_coding_model_eval_mock_scores_routing_and_red_block(tmp_path: Path) -> None:
    output = tmp_path / "coding.json"
    result = run_script(str(CODING), "--mode", "mock", "--output", str(output))

    assert result.returncode == 0, result.stderr
    report = load_output(output)
    assert report["metrics"]["route_correctness"] == 1.0
    assert report["metrics"]["acceptance_rate"] == 1.0
    assert report["metrics"]["rework_rate"] == 0.25
    assert report["metrics"]["sensitive_externalization_incidents"] == 0
    red_detail = [item for item in report["details"] if item["id"] == "red-block"][0]
    assert red_detail["blocked"] is True
    assert red_detail["externalized"] is False
    secret_detail = [item for item in report["details"] if item["id"] == "secret-content-block"][0]
    assert secret_detail["blocked"] is True
    assert secret_detail["externalized"] is False


def test_coding_model_eval_counts_sensitive_externalization_incident(tmp_path: Path) -> None:
    live_response = tmp_path / "coding_live_response.json"
    live_response.write_text(
        json.dumps({"tasks": [{"id": "secret-content-block", "actual_route": "mcp_fast_coding", "externalized": True}]}),
        encoding="utf-8",
    )
    output = tmp_path / "coding_incident.json"

    result = run_script(str(CODING), "--mode", "live", "--live-response", str(live_response), "--output", str(output))

    assert result.returncode == 0, result.stderr
    report = load_output(output)
    assert report["metrics"]["sensitive_externalization_incidents"] == 1


def test_live_mode_without_bridge_records_skip(tmp_path: Path) -> None:
    output = tmp_path / "live.json"
    result = run_script(str(RESEARCH), "--mode", "live", "--output", str(output))

    assert result.returncode == 0, result.stderr
    report = load_output(output)
    assert report["status"] == "skipped_no_mcp_bridge"
    assert report["target_mcps"]
    assert report["score"] == 0.0


def test_live_mode_with_sanitized_response_scores(tmp_path: Path) -> None:
    fixture = load_output(RESEARCH_FIXTURE)
    live_response = tmp_path / "live_response.json"
    live_response.write_text(json.dumps(fixture["mock_response"]), encoding="utf-8")
    output = tmp_path / "live_scored.json"

    result = run_script(str(RESEARCH), "--mode", "live", "--live-response", str(live_response), "--output", str(output))

    assert result.returncode == 0, result.stderr
    report = load_output(output)
    assert report["mode"] == "live"
    assert report["status"] == "completed"
    assert report["metrics"]["faithfulness"] == 1.0
