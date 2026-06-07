from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MEMORY_DIR = ROOT / "scripts" / "memory"
if str(MEMORY_DIR) not in sys.path:
    sys.path.insert(0, str(MEMORY_DIR))

from memory_node import MemoryNodeValidationError  # noqa: E402
from tree_store import TreeStore, TreeStorePathError  # noqa: E402


PROJECT = "p-threat-model-project"
OTHER_PROJECT = "p-threat-model-other"
SAFE_LOG_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def red_text() -> str:
    return "tok" + "en=abcd1234"


def base_node(**overrides):
    payload = {
        "schema_version": "ralph_memory_node_v2",
        "node_id": "node_threat_001",
        "project_id": PROJECT,
        "workspace_instance_id": "workspace-threat",
        "repo_remote_hash": "remotehash",
        "branch": "main",
        "commit": "abc123",
        "session_id": "session-threat",
        "memory_type": "fact",
        "sensitivity": "YELLOW",
        "authority": "non_authoritative",
        "summary": "Threat invariant storage remains non-authoritative.",
        "detailed_summary": "Safe detail for deterministic invariant tests.",
        "trigger": {"terms": ["threat-model", "invariant"]},
        "topic_tags": ["memory-tree"],
        "entities": ["TreeStore"],
        "source_paths": ["docs/architecture/memory-threat-model-v2.md"],
        "source_description": "",
        "raw_ref": None,
        "links": [],
        "salience": {"recency": 0.5},
        "quality": {"confidence": 0.9, "validation_status": "pass"},
        "created_at": "2026-06-07T00:00:00+00:00",
        "updated_at": "2026-06-07T00:00:00+00:00",
        "compaction_reason": "phase_03_invariant_test",
    }
    payload.update(overrides)
    return payload


def empty_or_missing(path: Path) -> bool:
    return not path.exists() or not any(path.iterdir())


def test_red_is_rejected_by_memory_node_storage(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)

    with pytest.raises(MemoryNodeValidationError):
        store.create_node(base_node(sensitivity="RED"))

    assert empty_or_missing(store.nodes_dir(PROJECT))


def test_red_raw_is_rejected(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)

    with pytest.raises(MemoryNodeValidationError):
        store.save_raw(PROJECT, red_text(), sensitivity="YELLOW")
    with pytest.raises(MemoryNodeValidationError):
        store.save_raw(PROJECT, "safe body", sensitivity="RED")

    assert empty_or_missing(store.raw_dir(PROJECT))


def test_memory_authority_must_be_non_authoritative(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)

    with pytest.raises(MemoryNodeValidationError):
        store.create_node(base_node(authority="authoritative"))

    assert empty_or_missing(store.nodes_dir(PROJECT))


def test_missing_provenance_is_rejected(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)

    with pytest.raises(MemoryNodeValidationError):
        store.create_node(base_node(source_paths=[], source_description=""))

    assert empty_or_missing(store.nodes_dir(PROJECT))


def test_path_traversal_is_rejected(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)

    with pytest.raises(MemoryNodeValidationError):
        store.create_node(base_node(node_id="../escape"))
    with pytest.raises(TreeStorePathError):
        store.load_node(PROJECT, "../escape")
    with pytest.raises(TreeStorePathError):
        store.list_nodes("../project")

    assert empty_or_missing(store.nodes_dir(PROJECT))


def test_raw_body_is_not_returned_by_default_node_listing(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    raw_body = "safe raw body for explicit depth two diagnostics only"
    saved = store.save_raw(PROJECT, raw_body, sensitivity="YELLOW")
    store.create_node(base_node(raw_ref={"sha256": saved["sha256"], "safe": True, "sensitivity": "YELLOW"}))

    listed = store.list_nodes(PROJECT)
    serialized = json.dumps(listed, ensure_ascii=True, sort_keys=True)

    assert [node["node_id"] for node in listed] == ["node_threat_001"]
    assert saved["sha256"] in serialized
    assert raw_body not in serialized


def test_snapshots_are_created_before_restore_tests(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    store.create_node(base_node())
    snapshot_id = store.snapshot_tree(PROJECT, "snapshot_before_restore")
    snapshot_path = store.snapshots_dir(PROJECT) / snapshot_id

    assert snapshot_path.is_dir()
    assert (snapshot_path / "manifest.json").is_file()

    store.update_node(PROJECT, "node_threat_001", {"summary": "Changed after snapshot."})
    store.restore_snapshot(PROJECT, snapshot_id)

    assert store.load_node(PROJECT, "node_threat_001")["summary"] == base_node()["summary"]


def test_corrupt_node_files_do_not_crash_list_operations(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    store.ensure_layout(PROJECT)
    store.node_path(PROJECT, "node_corrupt_001").write_text("{", encoding="utf-8")

    assert store.load_node(PROJECT, "node_corrupt_001") is None
    assert store.list_nodes(PROJECT) == []


def test_wrong_project_path_isolation(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    saved = store.save_raw(PROJECT, "safe project-scoped raw body", sensitivity="YELLOW")
    store.create_node(base_node(raw_ref={"sha256": saved["sha256"], "safe": True}))

    assert store.load_node(OTHER_PROJECT, "node_threat_001") is None
    assert store.list_nodes(OTHER_PROJECT) == []
    assert store.read_raw(OTHER_PROJECT, saved["sha256"]) is None
    assert store.project_tree(PROJECT) != store.project_tree(OTHER_PROJECT)


def test_node_ids_and_hashes_are_safe_to_log(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    raw_body = "safe raw detail that must not enter log-shaped data"
    saved = store.save_raw(PROJECT, raw_body, sensitivity="YELLOW")
    store.create_node(base_node(raw_ref={"sha256": saved["sha256"], "safe": True}))

    lookup = store.find_by_hash(PROJECT, saved["sha256"])
    usage_text = (store.project_tree(PROJECT) / "usage.jsonl").read_text(encoding="utf-8")

    assert SHA256_RE.fullmatch(saved["sha256"])
    assert lookup == {"raw_exists": True, "node_ids": ["node_threat_001"]}
    assert SAFE_LOG_ID_RE.fullmatch(lookup["node_ids"][0])
    assert raw_body not in usage_text
    assert saved["path"] not in usage_text


def test_memory_trace_like_data_does_not_include_raw_body(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    raw_body = "safe raw content reserved for explicit raw-open diagnostics"
    saved = store.save_raw(PROJECT, raw_body, sensitivity="YELLOW")
    store.create_node(base_node(raw_ref={"sha256": saved["sha256"], "safe": True}))
    usage_events = [
        json.loads(line)
        for line in (store.project_tree(PROJECT) / "usage.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    trace_like = {
        "selected_memory_ids": [node["node_id"] for node in store.list_nodes(PROJECT)],
        "raw_ref_hashes": [node["raw_ref"]["sha256"] for node in store.list_nodes(PROJECT) if node.get("raw_ref")],
        "usage_events": usage_events,
    }

    serialized = json.dumps(trace_like, ensure_ascii=True, sort_keys=True)
    assert raw_body not in serialized
    assert saved["path"] not in serialized
    assert trace_like["usage_events"][0]["event"] == "node_written"


@pytest.mark.parametrize(
    "overrides",
    [
        {"sensitivity": "RED", "summary": red_text()},
        {"sensitivity": "RED", "trigger": {"terms": [red_text()]}},
        {"sensitivity": "YELLOW", "summary": red_text()},
        {"sensitivity": "YELLOW", "trigger": {"terms": [red_text()]}},
    ],
)
def test_sensitive_material_is_not_stored_in_summary_or_trigger(tmp_path: Path, overrides) -> None:
    store = TreeStore(tmp_path)

    with pytest.raises(MemoryNodeValidationError):
        store.create_node(base_node(**overrides))

    assert empty_or_missing(store.nodes_dir(PROJECT))
