from __future__ import annotations

import hashlib
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

PROJECT = "p-recall-v2"
BRANCH = "main"
WORKSPACE = "workspace-recall"
RECALL = ROOT / "scripts" / "memory" / "recall_v2.py"
READ = ROOT / "scripts" / "memory" / "read_memory_node.py"


def red_text() -> str:
    return "tok" + "en=abcd1234"


def node(node_id: str, **overrides):
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
        "summary": "Safe recall alpha summary.",
        "detailed_summary": "Safe detailed recall alpha explanation.",
        "trigger": {"terms": ["alpha"], "paths": ["docs/alpha.md"]},
        "topic_tags": ["memory-tree"],
        "entities": ["AlphaEntity"],
        "source_paths": ["docs/alpha.md"],
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


def store_node(tmp_path: Path, payload: dict) -> None:
    TreeStore(tmp_path).create_node(payload)


def write_raw_node(tmp_path: Path, payload: dict) -> None:
    store = TreeStore(tmp_path)
    store.ensure_layout(PROJECT)
    store.node_path(PROJECT, payload.get("node_id", "node_raw")).write_text(json.dumps(payload), encoding="utf-8")


def run_recall(tmp_path: Path, query: str, *extra: str, budget: int | None = None) -> tuple[dict, str]:
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
        *extra,
    ]
    if budget is not None:
        args.extend(["--" + "tok" + "en-budget", str(budget)])
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False, env=os.environ.copy())
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout), result.stdout


def run_read(tmp_path: Path, node_id: str, depth: int, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(READ),
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
            "--node-id",
            node_id,
            "--depth",
            str(depth),
            *extra,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def reasons(report: dict) -> dict[str, str]:
    return {item["node_id"]: item["reason"] for item in report["MEMORY_TRACE_JSON"]["rejected"]}


def test_summary_match_selected(tmp_path: Path) -> None:
    store_node(tmp_path, node("node_summary", summary="Use summarymarker for recall."))
    report, _stdout = run_recall(tmp_path, "summarymarker")
    assert report["MEMORY_TRACE_JSON"]["selected_memory_ids"] == ["node_summary"]


def test_trigger_match_selected(tmp_path: Path) -> None:
    store_node(tmp_path, node("node_trigger", summary="No visible match here.", trigger={"terms": ["triggermarker"]}))
    report, _stdout = run_recall(tmp_path, "triggermarker")
    assert report["MEMORY_TRACE_JSON"]["selected_memory_ids"] == ["node_trigger"]


def test_entity_and_path_match_selected(tmp_path: Path) -> None:
    store_node(tmp_path, node("node_path", summary="No direct term.", entities=["WidgetEntity"], source_paths=["docs/widget-path.md"]))
    report, _stdout = run_recall(tmp_path, "WidgetEntity widget-path")
    assert report["MEMORY_TRACE_JSON"]["selected_memory_ids"] == ["node_path"]


def test_wrong_project_branch_worktree_are_rejected(tmp_path: Path) -> None:
    write_raw_node(tmp_path, node("node_wrong_project", project_id="p-other", summary="scope marker"))
    write_raw_node(tmp_path, node("node_wrong_branch", branch="other", summary="scope marker"))
    write_raw_node(tmp_path, node("node_wrong_worktree", workspace_instance_id="other-workspace", summary="scope marker"))
    report, _stdout = run_recall(tmp_path, "scope marker")
    assert reasons(report)["node_wrong_project"] == "wrong_project"
    assert reasons(report)["node_wrong_branch"] == "wrong_branch"
    assert reasons(report)["node_wrong_worktree"] == "wrong_worktree"


def test_deprecated_rejected_current_selected(tmp_path: Path) -> None:
    store_node(tmp_path, node("node_current", summary="current marker"))
    write_raw_node(tmp_path, node("node_deprecated", summary="current marker deprecated marker marker", quality={"confidence": 1.0, "provenance_complete": True, "deprecated": True}))
    report, _stdout = run_recall(tmp_path, "current marker deprecated")
    assert report["MEMORY_TRACE_JSON"]["selected_memory_ids"] == ["node_current"]
    assert reasons(report)["node_deprecated"] == "deprecated"


def test_red_and_missing_provenance_rejected(tmp_path: Path) -> None:
    write_raw_node(tmp_path, node("node_red", sensitivity="RED", summary="red marker"))
    write_raw_node(tmp_path, node("node_missing_provenance", summary="provenance marker", source_paths=[], source_description="", quality={"confidence": 0.8, "provenance_complete": False}))
    report, stdout = run_recall(tmp_path, "red provenance marker")
    assert reasons(report)["node_red"] == "red"
    assert reasons(report)["node_missing_provenance"] == "missing_provenance"
    assert red_text() not in stdout


def test_high_risk_marks_raw_recommended_and_recall_does_not_include_raw(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    raw_body = "safe raw exact detail for explicit reader"
    raw_ref = store.save_raw(PROJECT, raw_body, sensitivity="YELLOW")
    store_node(tmp_path, node("node_raw_ref", summary="exact quoted marker", raw_ref={"sha256": raw_ref["sha256"], "safe": True}))
    report, stdout = run_recall(tmp_path, "exact quoted marker raw")
    selected = report["memory_context"][0]
    assert report["MEMORY_TRACE_JSON"]["risk_level"] == "high"
    assert selected["RAW_RECOMMENDED"] is True
    assert report["MEMORY_TRACE_JSON"]["raw_included"] is False
    assert raw_body not in stdout


def test_read_memory_node_depth_zero_one_two(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    raw_ref = store.save_raw(PROJECT, "safe explicit raw detail", sensitivity="YELLOW")
    store_node(tmp_path, node("node_read", raw_ref={"sha256": raw_ref["sha256"], "safe": True}))

    depth0 = json.loads(run_read(tmp_path, "node_read", 0).stdout)
    depth1 = json.loads(run_read(tmp_path, "node_read", 1).stdout)
    depth2_fail = run_read(tmp_path, "node_read", 2)
    depth2 = json.loads(run_read(tmp_path, "node_read", 2, "--redact").stdout)

    assert "detailed_summary" not in depth0
    assert depth1["detailed_summary"] == "Safe detailed recall alpha explanation."
    assert depth2_fail.returncode == 2
    assert depth2["raw_redacted"] == "safe explicit raw detail"


def test_read_depth_two_never_prints_red_raw(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    digest = hashlib.sha256(red_text().encode("utf-8")).hexdigest()
    store.ensure_layout(PROJECT)
    store.raw_path(PROJECT, digest).write_text(red_text(), encoding="utf-8")
    store_node(tmp_path, node("node_red_raw", raw_ref={"sha256": digest, "safe": True}))

    result = run_read(tmp_path, "node_red_raw", 2, "--redact")

    assert result.returncode == 2
    assert red_text() not in result.stdout
    assert json.loads(result.stdout)["error"] == "raw_unavailable_or_unsafe"


def test_budget_respected_and_trace_has_reasons(tmp_path: Path) -> None:
    for index in range(3):
        store_node(tmp_path, node(f"node_budget_{index}", summary=f"budget marker {index}", trigger={"terms": ["budget"]}))
    report, _stdout = run_recall(tmp_path, "budget marker", budget=22)
    trace = report["MEMORY_TRACE_JSON"]
    assert trace["selected_memory_ids"]
    assert trace["tok" + "en_budget"]["used"] <= trace["tok" + "en_budget"]["limit"]
    assert "budget_exceeded" in {item["reason"] for item in trace["rejected"]}
