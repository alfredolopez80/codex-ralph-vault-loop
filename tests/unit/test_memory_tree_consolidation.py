from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MEMORY_DIR = ROOT / "scripts" / "memory"
if str(MEMORY_DIR) not in sys.path:
    sys.path.insert(0, str(MEMORY_DIR))

from consolidate_tree import consolidate_tree  # noqa: E402
from recall_v2 import Context, recall  # noqa: E402
from tree_store import TreeStore, atomic_write_json  # noqa: E402

PROJECT = "p-consolidation"
WORKSPACE = "workspace-consolidation"
BRANCH = "main"


def node(node_id: str, **overrides):
    payload = {
        "schema_version": "ralph_memory_node_v2",
        "node_id": node_id,
        "project_id": PROJECT,
        "workspace_instance_id": WORKSPACE,
        "repo_remote_hash": "remotehash",
        "branch": BRANCH,
        "created_on_branch": BRANCH,
        "visibility": "branch_local",
        "promotion_status": "not_promoted",
        "promotion_evidence": {},
        "commit": "abc123",
        "session_id": "session-consolidation",
        "memory_type": "fact",
        "sensitivity": "YELLOW",
        "authority": "non_authoritative",
        "summary": "Consolidation safe summary marker.",
        "detailed_summary": "Consolidation safe detailed summary.",
        "trigger": {"terms": ["consolidation", "marker"]},
        "topic_tags": ["consolidation"],
        "entities": ["ConsolidationNode"],
        "source_paths": ["docs/consolidation.md"],
        "source_description": "",
        "raw_ref": None,
        "links": [],
        "salience": {"validation": 0.5},
        "quality": {"confidence": 0.8, "provenance_complete": True, "validation_status": "pass", "stale": False, "deprecated": False},
        "created_at": "2026-06-07T00:00:00+00:00",
        "updated_at": "2026-06-07T00:00:00+00:00",
        "compaction_reason": "unit_test",
    }
    payload.update(overrides)
    return payload


def store_node(tmp_path: Path, payload: dict) -> None:
    TreeStore(tmp_path).create_node(payload)


def run_recall(tmp_path: Path, query: str) -> dict:
    return recall(query, Context(tmp_path, "consolidation", PROJECT, WORKSPACE, BRANCH), tmp_path)


def reasons(report: dict) -> dict[str, str]:
    return {item["node_id"]: item["reason"] for item in report["MEMORY_TRACE_JSON"]["rejected"]}


def red_text() -> str:
    return "tok" + "en=abcd1234"


def test_dry_run_no_mutation(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    store.create_node(node("node_a", topic_tags=["hub-topic"], summary="A hub topic marker."))
    store.create_node(node("node_b", topic_tags=["hub-topic"], summary="B hub topic marker.", source_paths=["docs/b.md"]))

    report = consolidate_tree(store, PROJECT, BRANCH, write=False)

    assert report["dry_run"] is True
    assert report["virtual_hubs"]
    assert not list(store.snapshots_dir(PROJECT).iterdir())
    assert [item["node_id"] for item in store.list_nodes(PROJECT)] == ["node_a", "node_b"]


def test_duplicate_detection(tmp_path: Path) -> None:
    store_node(tmp_path, node("node_dupe_a", summary="Duplicate safe operational rule.", source_paths=["docs/rule.md"]))
    store_node(tmp_path, node("node_dupe_b", summary="Duplicate safe operational rule.", source_paths=["docs/rule.md"]))

    report = consolidate_tree(TreeStore(tmp_path), PROJECT, BRANCH)

    assert report["duplicates"] == [{"canonical": "node_dupe_a", "duplicate": "node_dupe_b", "reason": "duplicate_overlap"}]


def test_consolidation_ignores_other_branch_local_nodes(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    store.create_node(node("node_active_branch", summary="Duplicate branch scoped rule.", source_paths=["docs/active.md"]))
    store.create_node(
        node(
            "node_other_branch",
            branch="feature-other",
            created_on_branch="feature-other",
            summary="Duplicate branch scoped rule.",
            source_paths=["docs/other.md"],
        )
    )

    report = consolidate_tree(store, PROJECT, BRANCH, write=True)

    assert {"node_id": "node_other_branch", "reason": "wrong_branch_scope"} in report["skipped"]
    assert report["duplicates"] == []
    assert store.load_node(PROJECT, "node_other_branch")["quality"].get("duplicate_of") is None


def test_write_creates_snapshot_and_virtual_hub_is_raw_free(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    store.create_node(node("node_hub_a", topic_tags=["cluster"], summary="Cluster alpha marker."))
    store.create_node(node("node_hub_b", topic_tags=["cluster"], summary="Cluster beta marker.", source_paths=["docs/b.md"]))

    report = consolidate_tree(store, PROJECT, BRANCH, write=True)

    assert report["snapshot_id"]
    assert (store.snapshots_dir(PROJECT) / report["snapshot_id"]).exists()
    hub_ids = [item["node_id"] for item in report["virtual_hubs"]]
    assert hub_ids
    hub = store.load_node(PROJECT, hub_ids[0])
    assert hub["memory_type"] == "hub"
    assert hub["raw_ref"] is None
    assert hub["quality"]["synthetic"] is True


def test_restore_on_simulated_failure(tmp_path: Path, monkeypatch) -> None:
    store = TreeStore(tmp_path)
    store.create_node(node("node_dupe_a", summary="Duplicate safe rule."))
    store.create_node(node("node_dupe_b", summary="Duplicate safe rule.", source_paths=["docs/b.md"]))

    def fail_update(*_args, **_kwargs):
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(store, "update_node", fail_update)
    report = consolidate_tree(store, PROJECT, BRANCH, write=True)

    assert report["error"] == "write_failed"
    assert report["restored_from_snapshot"] is True
    assert store.load_node(PROJECT, "node_dupe_b")["quality"].get("duplicate_of") is None


def test_superseded_stale_rule_rejected_by_recall_v2(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    store.create_node(node("node_old_rule", memory_type="rule", summary="Old threshold rule says limit 5.", topic_tags=["threshold"], updated_at="2026-01-01T00:00:00+00:00"))
    store.create_node(
        node(
            "node_new_rule",
            memory_type="rule",
            summary="New current threshold rule says limit 8.",
            topic_tags=["threshold"],
            source_paths=["docs/new-rule.md"],
            quality={"confidence": 0.9, "provenance_complete": True, "validation_status": "pass", "supersedes_node_ids": ["node_old_rule"]},
            updated_at="2026-06-07T00:00:00+00:00",
        )
    )

    consolidate_tree(store, PROJECT, BRANCH, write=True)
    report = run_recall(tmp_path, "new current threshold")

    assert report["MEMORY_TRACE_JSON"]["selected_memory_ids"][0] == "node_new_rule"
    assert reasons(report)["node_old_rule"] == "deprecated"


def test_graph_hop_recall_uses_safe_link_metadata(tmp_path: Path) -> None:
    store_node(tmp_path, node("node_target", summary="Target safe node.", topic_tags=["target-graph"], source_paths=["docs/target.md"]))
    store_node(
        tmp_path,
        node(
            "node_source",
            summary="Source node without direct ladder wording.",
            topic_tags=["source-graph"],
            source_paths=["docs/source.md"],
            quality={"confidence": 0.85, "provenance_complete": True, "validation_status": "pass", "link_hints": [{"relation": "supports", "target_node_id": "node_target", "evidence": "safe ladder evidence"}]},
        ),
    )

    consolidate_tree(TreeStore(tmp_path), PROJECT, BRANCH, write=True)
    report = run_recall(tmp_path, "ladder evidence")

    assert report["MEMORY_TRACE_JSON"]["selected_memory_ids"][0] == "node_source"


def test_negative_memory_selected_for_risky_task(tmp_path: Path) -> None:
    store_node(
        tmp_path,
        node(
            "node_negative",
            memory_type="negative_rule",
            summary="Do not repeat shortcut validation for release gates.",
            trigger={"terms": ["shortcut", "validation", "release"]},
            quality={"confidence": 0.86, "provenance_complete": True, "validation_status": "pass", "reason": "Shortcut validation hid a release gate issue.", "validation_evidence": ["focused regression passed"]},
        ),
    )

    report = run_recall(tmp_path, "avoid shortcut validation risk")

    assert report["MEMORY_TRACE_JSON"]["selected_memory_ids"] == ["node_negative"]
    assert report["memory_context"][0]["NEGATIVE_MEMORY"] is True
    assert "Shortcut validation" in report["memory_context"][0]["warning_reason"]


def test_red_skipped_and_explain_output_sanitized(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    store.create_node(node("node_safe_a", summary="Sanitized duplicate marker.", source_paths=["docs/a.md"]))
    store.create_node(node("node_safe_b", summary="Sanitized duplicate marker.", source_paths=["docs/b.md"]))
    unsafe = node("node_red", sensitivity="RED", summary=red_text(), source_paths=["docs/red.md"])
    store.ensure_layout(PROJECT)
    atomic_write_json(store.node_path(PROJECT, "node_red"), unsafe)

    report = consolidate_tree(store, PROJECT, BRANCH, write=False, explain=True)
    rendered = json.dumps(report, sort_keys=True)

    assert {"node_id": "node_red", "reason": "red"} in report["skipped"]
    assert report["explain"]
    assert red_text() not in rendered
    assert "Sanitized duplicate marker." not in rendered
