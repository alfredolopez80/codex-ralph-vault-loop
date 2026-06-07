from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MEMORY_DIR = ROOT / "scripts" / "memory"
if str(MEMORY_DIR) not in sys.path:
    sys.path.insert(0, str(MEMORY_DIR))

from promote_branch_memory import promote_branch_memory  # noqa: E402
from recall_v2 import Context, recall  # noqa: E402
from tree_store import TreeStore  # noqa: E402

PROJECT = "p-branch-promotion"
WORKSPACE = "workspace-branch"


def node(node_id: str, **overrides):
    payload = {
        "schema_version": "ralph_memory_node_v2",
        "node_id": node_id,
        "project_id": PROJECT,
        "workspace_instance_id": WORKSPACE,
        "repo_remote_hash": "remotehash",
        "branch": "feature/tree",
        "created_on_branch": "feature/tree",
        "visibility": "branch_local",
        "promotion_status": "not_promoted",
        "promotion_evidence": {},
        "commit": "abc123",
        "session_id": "session-branch",
        "memory_type": "fact",
        "sensitivity": "YELLOW",
        "authority": "non_authoritative",
        "summary": "branch marker safe operational memory",
        "detailed_summary": "branch marker detailed safe memory",
        "trigger": {"terms": ["branch", "marker"]},
        "topic_tags": ["branch-memory"],
        "entities": ["BranchMemory"],
        "source_paths": ["docs/branch-memory.md"],
        "source_description": "",
        "raw_ref": None,
        "links": [],
        "salience": {"validation": 0.5},
        "quality": {"confidence": 0.8, "provenance_complete": True, "stale": False, "deprecated": False},
        "created_at": "2026-06-07T00:00:00+00:00",
        "updated_at": "2026-06-07T00:00:00+00:00",
        "compaction_reason": "unit_test",
    }
    payload.update(overrides)
    return payload


def store_node(tmp_path: Path, payload: dict) -> None:
    TreeStore(tmp_path).create_node(payload)


def run_recall(tmp_path: Path, branch: str, query: str = "branch marker") -> dict:
    context = Context(tmp_path, "branch-project", PROJECT, WORKSPACE, branch)
    return recall(query, context, tmp_path)


def reasons(report: dict) -> dict[str, str]:
    return {item["node_id"]: item["reason"] for item in report["MEMORY_TRACE_JSON"]["rejected"]}


def promotion_evidence() -> dict:
    return {"tests_passed": True, "gates_passed": True, "tests": ["pytest"], "gates": ["minimal"]}


def test_branch_local_rejected_from_another_branch(tmp_path: Path) -> None:
    store_node(tmp_path, node("node_branch_local"))

    report = run_recall(tmp_path, "main")

    assert report["MEMORY_TRACE_JSON"]["selected_memory_ids"] == []
    assert reasons(report)["node_branch_local"] == "wrong_branch"


def test_branch_local_accepted_on_same_branch(tmp_path: Path) -> None:
    store_node(tmp_path, node("node_branch_local"))

    report = run_recall(tmp_path, "feature/tree")

    assert report["MEMORY_TRACE_JSON"]["selected_memory_ids"] == ["node_branch_local"]


def test_main_promoted_visible_from_feature_branch(tmp_path: Path) -> None:
    store_node(tmp_path, node("node_main_promoted", branch="main", created_on_branch="main", visibility="main_promoted"))

    report = run_recall(tmp_path, "feature/tree")

    assert report["MEMORY_TRACE_JSON"]["selected_memory_ids"] == ["node_main_promoted"]


def test_merge_candidate_visible_only_with_label_and_labeled(tmp_path: Path) -> None:
    store_node(tmp_path, node("node_merge_candidate", visibility="merge_candidate", promotion_status="candidate"))

    unlabeled = run_recall(tmp_path, "feature/tree")
    labeled = run_recall(tmp_path, "feature/tree", "merge_candidate branch marker")

    assert reasons(unlabeled)["node_merge_candidate"] == "merge_candidate_unlabeled"
    assert labeled["MEMORY_TRACE_JSON"]["selected_memory_ids"] == ["node_merge_candidate"]
    assert labeled["memory_context"][0]["visibility"] == "merge_candidate"
    assert labeled["memory_context"][0]["MERGE_CANDIDATE"] is True


def test_conflict_and_deprecated_on_merge_not_injected(tmp_path: Path) -> None:
    store_node(tmp_path, node("node_conflict", visibility="conflict"))
    store_node(tmp_path, node("node_deprecated_merge", visibility="deprecated_on_merge"))

    report = run_recall(tmp_path, "feature/tree")

    assert report["MEMORY_TRACE_JSON"]["selected_memory_ids"] == []
    assert reasons(report)["node_conflict"] == "conflict"
    assert reasons(report)["node_deprecated_merge"] == "deprecated_on_merge"


def test_promotion_requires_evidence(tmp_path: Path) -> None:
    store_node(tmp_path, node("node_candidate", visibility="merge_candidate", promotion_status="candidate"))

    report = promote_branch_memory(TreeStore(tmp_path), PROJECT, "feature/tree")

    skipped = report["skipped"][0]
    assert skipped["node_id"] == "node_candidate"
    assert "missing_tests_evidence" in skipped["reasons"]
    assert "missing_gates_evidence" in skipped["reasons"]


def test_dry_run_does_not_mutate(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    store.create_node(node("node_candidate", visibility="merge_candidate", promotion_status="candidate", promotion_evidence=promotion_evidence()))

    report = promote_branch_memory(store, PROJECT, "feature/tree", write=False)

    assert report["dry_run"] is True
    assert report["candidates"] == [{"node_id": "node_candidate", "visibility": "merge_candidate"}]
    assert report["snapshot_id"] is None
    assert store.load_node(PROJECT, "node_candidate")["visibility"] == "merge_candidate"


def test_write_creates_snapshot_and_promotes(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    store.create_node(node("node_candidate", visibility="merge_candidate", promotion_status="candidate", promotion_evidence=promotion_evidence()))

    report = promote_branch_memory(store, PROJECT, "feature/tree", write=True)

    promoted = store.load_node(PROJECT, "node_candidate")
    assert report["snapshot_id"]
    assert (store.snapshots_dir(PROJECT) / report["snapshot_id"]).exists()
    assert report["promoted"] == [{"node_id": "node_candidate", "visibility": "main_promoted"}]
    assert promoted["visibility"] == "main_promoted"
    assert promoted["branch"] == "main"


def test_simulated_write_failure_restores_snapshot(tmp_path: Path, monkeypatch) -> None:
    store = TreeStore(tmp_path)
    store.create_node(node("node_candidate", visibility="merge_candidate", promotion_status="candidate", promotion_evidence=promotion_evidence()))

    def fail_update(*_args, **_kwargs):
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(store, "update_node", fail_update)
    report = promote_branch_memory(store, PROJECT, "feature/tree", write=True)

    assert report["error"] == "write_failed"
    assert report["restored_from_snapshot"] is True
    assert store.load_node(PROJECT, "node_candidate")["visibility"] == "merge_candidate"
