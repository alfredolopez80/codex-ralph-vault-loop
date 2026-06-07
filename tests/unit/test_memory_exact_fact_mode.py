from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MEMORY_DIR = ROOT / "scripts" / "memory"
if str(MEMORY_DIR) not in sys.path:
    sys.path.insert(0, str(MEMORY_DIR))

from tree_store import TreeStore  # noqa: E402

PROJECT = "p-exact-mode"
BRANCH = "main"
WORKSPACE = "workspace-exact"
RECALL = ROOT / "scripts" / "memory" / "recall_v2.py"


def node(node_id: str = "node_exact", **overrides):
    payload = {
        "schema_version": "ralph_memory_node_v2",
        "node_id": node_id,
        "project_id": PROJECT,
        "workspace_instance_id": WORKSPACE,
        "repo_remote_hash": "remotehash",
        "branch": BRANCH,
        "commit": "abc123",
        "session_id": "session-1",
        "memory_type": "fact",
        "sensitivity": "YELLOW",
        "authority": "non_authoritative",
        "summary": "Exact marker summary for recall.",
        "detailed_summary": "Detailed text must not be returned for exact high risk recall.",
        "trigger": {
            "terms": ["exact-marker", "run-tests.py", "MemoryNode", "selected_memory_ids"],
            "paths": ["scripts/gates/run-tests.py"],
            "functions": ["build_report"],
            "versions": ["v1.2.3"],
            "dates": ["2026-06-07"],
        },
        "topic_tags": ["memory-tree"],
        "entities": ["MemoryNode", "ExactMetric"],
        "source_paths": ["scripts/gates/run-tests.py"],
        "source_description": "",
        "raw_ref": None,
        "links": [],
        "salience": {"recency": 0.5, "validation": 0.5},
        "quality": {"confidence": 0.8, "provenance_complete": True, "validation_status": "pass", "stale": False, "deprecated": False},
        "created_at": "2026-06-07T00:00:00+00:00",
        "updated_at": "2026-06-07T00:00:00+00:00",
        "compaction_reason": "unit_test",
    }
    payload.update(overrides)
    return payload


def store_node(tmp_path: Path, payload: dict | None = None) -> None:
    TreeStore(tmp_path).create_node(payload or node())


def run_recall(tmp_path: Path, query: str, *, budget: int | None = None) -> tuple[dict, str]:
    args = [
        sys.executable,
        str(RECALL),
        "--project-root",
        str(tmp_path),
        "--project-id",
        PROJECT,
        "--ralph-home",
        str(tmp_path),
        "--branch",
        BRANCH,
        "--workspace-instance-id",
        WORKSPACE,
        "--query",
        query,
        "--json",
    ]
    if budget is not None:
        args.extend(["--" + "tok" + "en-budget", str(budget)])
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False, env=os.environ.copy())
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout), result.stdout


def assert_exact_high(report: dict) -> None:
    trace = report["MEMORY_TRACE_JSON"]
    assert trace["risk_level"] == "high"
    assert trace["raw_recommended"] is True
    assert trace["raw_included"] is False
    assert trace["exact_fact_mode"] is True


def test_exact_command_query_marks_high_risk(tmp_path: Path) -> None:
    store_node(tmp_path)
    report, _stdout = run_recall(tmp_path, "What exact command used run-tests.py exact-marker?")
    assert_exact_high(report)


def test_exact_path_query_marks_high_risk(tmp_path: Path) -> None:
    store_node(tmp_path)
    report, _stdout = run_recall(tmp_path, "What exact file path mentions scripts/gates/run-tests.py?")
    assert_exact_high(report)


def test_exact_function_and_class_queries_mark_high_risk(tmp_path: Path) -> None:
    store_node(tmp_path)
    function_report, _stdout = run_recall(tmp_path, "What exact function name build_report is stored?")
    class_report, _stdout = run_recall(tmp_path, "What exact class name MemoryNode is stored?")
    assert_exact_high(function_report)
    assert_exact_high(class_report)


def test_exact_benchmark_metric_date_version_number_queries_mark_high_risk(tmp_path: Path) -> None:
    store_node(tmp_path, node(summary="ExactMetric score was 42 on 2026-06-07 for v1.2.3."))
    metric_report, _stdout = run_recall(tmp_path, "What exact benchmark metric ExactMetric?")
    date_report, _stdout = run_recall(tmp_path, "What exact date 2026-06-07?")
    version_report, _stdout = run_recall(tmp_path, "What exact version v1.2.3?")
    number_report, _stdout = run_recall(tmp_path, "What exact number 42?")
    for report in (metric_report, date_report, version_report, number_report):
        assert_exact_high(report)


def test_quote_config_key_and_selected_memory_ids_queries_mark_high_risk(tmp_path: Path) -> None:
    store_node(tmp_path, node(summary="Trace selected_memory_ids mention exact-marker and config key RALPH_MEMORY_RECALL_ENGINE."))
    quote_report, _stdout = run_recall(tmp_path, "Quote prior wording for exact-marker")
    config_report, _stdout = run_recall(tmp_path, "Does config key RALPH_MEMORY_RECALL_ENGINE exist?")
    trace_report, _stdout = run_recall(tmp_path, "What exact selected_memory_ids from prior trace?")
    for report in (quote_report, config_report, trace_report):
        assert_exact_high(report)


def test_conceptual_query_remains_low_or_medium_risk(tmp_path: Path) -> None:
    store_node(tmp_path)
    report, _stdout = run_recall(tmp_path, "How should memory-tree recall work?")
    assert report["MEMORY_TRACE_JSON"]["risk_level"] in {"low", "medium"}
    assert report["MEMORY_TRACE_JSON"]["exact_fact_mode"] is False


def test_raw_is_never_included_and_high_risk_returns_summary_trigger_only(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    raw_body = "safe raw body must not appear"
    raw_ref = store.save_raw(PROJECT, raw_body, sensitivity="YELLOW")
    store_node(tmp_path, node(raw_ref={"sha256": raw_ref["sha256"], "safe": True}))
    report, stdout = run_recall(tmp_path, "Quote exact-marker")
    selected = report["memory_context"][0]
    assert selected["raw_included"] is False
    assert "detailed_summary" not in selected
    assert "source_paths" not in selected
    assert "trigger" in selected
    assert raw_body not in stdout


def test_suggested_read_command_appears_only_when_node_selected(tmp_path: Path) -> None:
    store_node(tmp_path)
    selected_report, _stdout = run_recall(tmp_path, "Quote exact-marker")
    empty_report, _stdout = run_recall(tmp_path, "Quote absent-marker")
    selected = selected_report["memory_context"][0]
    assert selected["suggested_read_command"] == "python3 scripts/memory/read_memory_node.py --project-root . --node-id node_exact --depth 2 --redact"
    assert empty_report["memory_context"] == []
    assert "suggested_read_command" not in json.dumps(empty_report)


def test_budget_still_respected_in_exact_mode(tmp_path: Path) -> None:
    for index in range(3):
        store_node(tmp_path, node(f"node_exact_{index}", summary=f"exact-marker budget item {index}"))
    report, _stdout = run_recall(tmp_path, "Quote exact-marker", budget=28)
    trace = report["MEMORY_TRACE_JSON"]
    assert trace["tok" + "en_budget"]["used"] <= trace["tok" + "en_budget"]["limit"]
    assert "budget_exceeded" in {item["reason"] for item in trace["rejected"]}
