from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MEMORY_DIR = ROOT / "scripts" / "memory"
if str(MEMORY_DIR) not in sys.path:
    sys.path.insert(0, str(MEMORY_DIR))

from memory_node import MemoryNode, MemoryNodeValidationError, deterministic_node_id  # noqa: E402
from tree_store import TreeStore, TreeStoreError, TreeStorePathError  # noqa: E402


PROJECT = "p-test-project"
OTHER_PROJECT = "p-other-project"


def red_text() -> str:
    return "tok" + "en=abcd1234"


def red_json_text() -> str:
    return '{"tok' + 'en":"abcd1234"}'


def base_node(**overrides):
    payload = {
        "schema_version": "ralph_memory_node_v2",
        "node_id": "node_valid_001",
        "project_id": PROJECT,
        "workspace_instance_id": "workspace-1",
        "repo_remote_hash": "remotehash",
        "branch": "main",
        "commit": "abc123",
        "session_id": "session-1",
        "memory_type": "fact",
        "sensitivity": "YELLOW",
        "authority": "non_authoritative",
        "summary": "The tree store writes safe deterministic nodes.",
        "detailed_summary": "A longer safe summary for depth one retrieval.",
        "trigger": {"terms": ["tree", "store"], "paths": ["docs/architecture/memory-tree-v2.md"]},
        "topic_tags": ["memory-tree"],
        "entities": ["TreeStore"],
        "source_paths": ["docs/architecture/memory-tree-v2.md"],
        "source_description": "",
        "raw_ref": None,
        "links": [],
        "salience": {"recency": 0.5},
        "quality": {"confidence": 0.8, "validation_status": "pass"},
        "created_at": "2026-06-07T00:00:00+00:00",
        "updated_at": "2026-06-07T00:00:00+00:00",
        "compaction_reason": "unit_test",
    }
    payload.update(overrides)
    return payload


def test_valid_node_round_trip(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)

    created = store.create_node(base_node())
    loaded = store.load_node(PROJECT, "node_valid_001")

    assert loaded == created
    assert store.node_exists(PROJECT, "node_valid_001")
    assert [node["node_id"] for node in store.list_nodes(PROJECT)] == ["node_valid_001"]


def test_atomic_json_write_creates_valid_json(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)

    store.create_node(base_node())
    path = store.node_path(PROJECT, "node_valid_001")

    assert json.loads(path.read_text(encoding="utf-8"))["node_id"] == "node_valid_001"
    assert not list(path.parent.glob(".*.tmp"))


def test_raw_content_hash_round_trip(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    content = "safe raw detail for explicit diagnostic use"

    saved = store.save_raw(PROJECT, content, sensitivity="GREEN")

    assert saved["sha256"] == hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert store.read_raw(PROJECT, saved["sha256"]) == content
    assert store.find_by_hash(PROJECT, saved["sha256"])["raw_exists"] is True


def test_red_node_rejected(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)

    with pytest.raises(MemoryNodeValidationError):
        store.create_node(base_node(summary=red_text()))

    assert not store.node_path(PROJECT, "node_valid_001").exists()


def test_red_raw_rejected(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)

    with pytest.raises(MemoryNodeValidationError):
        store.save_raw(PROJECT, "safe text", sensitivity="RED")
    with pytest.raises(MemoryNodeValidationError):
        store.save_raw(PROJECT, red_text(), sensitivity="YELLOW")
    with pytest.raises(MemoryNodeValidationError):
        store.save_raw(PROJECT, "safe text", sensitivity="YELLOW", safe=False)
    with pytest.raises(MemoryNodeValidationError):
        store.save_raw(PROJECT, red_json_text(), sensitivity="YELLOW")

    assert not list(store.raw_dir(PROJECT).glob("*.txt")) if store.raw_dir(PROJECT).exists() else True


def test_quoted_sensitive_node_fields_rejected(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)

    with pytest.raises(MemoryNodeValidationError):
        store.create_node(base_node(trigger={"tok" + "en": "abcd1234"}))
    with pytest.raises(MemoryNodeValidationError):
        store.create_node(base_node(summary="`tok" + "en`: abcd1234"))


def test_missing_provenance_rejected(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)

    with pytest.raises(MemoryNodeValidationError):
        store.create_node(base_node(source_paths=[], source_description=""))


def test_authority_inversion_rejected(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)

    with pytest.raises(MemoryNodeValidationError):
        store.create_node(base_node(authority="authoritative"))


def test_path_traversal_rejected(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)

    with pytest.raises(MemoryNodeValidationError):
        store.create_node(base_node(node_id="../escape"))
    with pytest.raises(TreeStorePathError):
        store.load_node(PROJECT, "../escape")
    with pytest.raises(TreeStorePathError):
        store.load_node(PROJECT, "/tmp/escape")


def test_symlink_escape_rejected(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    root = store.ensure_layout(PROJECT)
    outside = tmp_path / "outside"
    outside.mkdir()
    nodes = root / "nodes"
    nodes.rmdir()
    nodes.symlink_to(outside, target_is_directory=True)

    with pytest.raises(TreeStorePathError):
        store.create_node(base_node())


def test_snapshot_and_restore(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    store.create_node(base_node())
    raw = store.save_raw(PROJECT, "safe restore payload")
    snapshot_id = store.snapshot_tree(PROJECT, "snapshot_001")

    store.update_node(PROJECT, "node_valid_001", {"summary": "Changed after snapshot."})
    store.restore_snapshot(PROJECT, snapshot_id)

    assert store.load_node(PROJECT, "node_valid_001")["summary"] == base_node()["summary"]
    assert store.read_raw(PROJECT, raw["sha256"]) == "safe restore payload"


def test_snapshot_rejects_source_symlink(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    store.create_node(base_node())
    outside = tmp_path / "outside.txt"
    outside.write_text("safe outside file", encoding="utf-8")
    (store.raw_dir(PROJECT) / "link.txt").symlink_to(outside)

    with pytest.raises(TreeStoreError):
        store.snapshot_tree(PROJECT, "snapshot_symlink")


def test_wrong_project_path_isolation(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    store.create_node(base_node())

    assert store.load_node(OTHER_PROJECT, "node_valid_001") is None
    assert store.list_nodes(OTHER_PROJECT) == []
    assert PROJECT in str(store.node_path(PROJECT, "node_valid_001"))
    assert OTHER_PROJECT in str(store.node_path(OTHER_PROJECT, "node_valid_001"))


def test_deterministic_node_id_when_input_is_deterministic() -> None:
    payload = base_node()
    payload.pop("node_id")

    assert deterministic_node_id(payload) == deterministic_node_id(dict(payload))
    assert MemoryNode.from_dict(payload).node_id == MemoryNode.from_dict(dict(payload)).node_id


def test_corrupted_node_file_handled_safely(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    store.create_node(base_node())
    store.node_path(PROJECT, "node_valid_001").write_text("{", encoding="utf-8")

    assert store.load_node(PROJECT, "node_valid_001") is None
    assert store.list_nodes(PROJECT) == []
