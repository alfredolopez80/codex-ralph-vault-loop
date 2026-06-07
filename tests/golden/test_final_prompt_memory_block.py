from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TASK_INTAKE = ROOT / "scripts" / "memory" / "task-intake.py"
FIXTURES = ROOT / "tests" / "golden" / "fixtures" / "final_prompt_memory_blocks"
MEMORY_DIR = ROOT / "scripts" / "memory"
if str(MEMORY_DIR) not in sys.path:
    sys.path.insert(0, str(MEMORY_DIR))

from recall_v2 import context_for  # noqa: E402
from tree_store import TreeStore  # noqa: E402

PROJECT = "codex-ralph-vault-loop"
PROJECT_ID = "p-golden-memory-block"
BRANCH = "codex/golden-memory"


def load_task_intake():
    spec = importlib.util.spec_from_file_location("task_intake_golden_memory", TASK_INTAKE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def node(root: Path, node_id: str, **overrides: Any) -> dict[str, Any]:
    context = context_for(root, PROJECT_ID, BRANCH)
    payload = {
        "schema_version": "ralph_memory_node_v2",
        "node_id": node_id,
        "project_id": PROJECT_ID,
        "workspace_instance_id": context.workspace_instance_id,
        "repo_remote_hash": "remotehash",
        "branch": BRANCH,
        "created_on_branch": BRANCH,
        "visibility": "branch_local",
        "promotion_status": "not_promoted",
        "promotion_evidence": {},
        "commit": "abc123",
        "session_id": "session-golden",
        "memory_type": "fact",
        "sensitivity": "YELLOW",
        "authority": "non_authoritative",
        "summary": "GOLDEN_RELEVANT_MEMORY selected memory reaches final prompt.",
        "detailed_summary": "GOLDEN_DETAIL_SHOULD_NOT_APPEAR",
        "trigger": {"terms": ["golden", "relevant", "memory"]},
        "topic_tags": ["golden-memory"],
        "entities": ["GoldenMemory"],
        "source_paths": ["docs/golden.md"],
        "source_description": "",
        "raw_ref": None,
        "links": [],
        "salience": {"validation": 0.5},
        "quality": {"confidence": 0.8, "provenance_complete": True, "validation_status": "pass", "stale": False, "deprecated": False},
        "created_at": "2026-06-07T00:00:00+00:00",
        "updated_at": "2026-06-07T00:00:00+00:00",
        "compaction_reason": "golden_test",
    }
    payload.update(overrides)
    return payload


def forbidden_legacy(*_args, **_kwargs):
    raise AssertionError("legacy recall should not run in tree golden test")


def test_tree_final_prompt_memory_block_is_safe_and_non_authoritative(monkeypatch, tmp_path: Path) -> None:
    task_intake = load_task_intake()
    store = TreeStore(tmp_path)
    raw_ref = store.save_raw(PROJECT_ID, "GOLDEN_RAW_SHOULD_NOT_APPEAR", sensitivity="YELLOW")
    store.create_node(node(tmp_path, "node_golden_relevant"))
    store.create_node(node(tmp_path, "node_golden_irrelevant", summary="OFFTOPIC_SENTINEL should stay out.", trigger={"terms": ["other-topic"]}, topic_tags=["other-topic"], entities=["OtherTopic"], source_paths=["docs/other.md"]))
    store.create_node(node(tmp_path, "node_golden_stale", summary="GOLDEN_STALE_MEMORY should stay out.", entities=["StaleTopic"], quality={"confidence": 0.8, "provenance_complete": True, "validation_status": "pass", "deprecated": True}, source_paths=["docs/stale.md"]))
    store.create_node(node(tmp_path, "node_golden_raw", summary="RAW_POINTER_SUMMARY safe raw pointer.", trigger={"terms": ["raw-pointer-only"]}, topic_tags=["raw-topic"], entities=["RawTopic"], raw_ref={"sha256": raw_ref["sha256"], "safe": True}, source_paths=["docs/raw.md"]))
    monkeypatch.setenv("RALPH_HOME", str(tmp_path))
    monkeypatch.setenv("RALPH_MEMORY_RECALL_ENGINE", "tree")

    payload = task_intake.build_task_intake_payload(
        prompt="Use golden relevant memory for final prompt",
        project=PROJECT,
        project_id=PROJECT_ID,
        workspace_root=str(tmp_path),
        branch=BRANCH,
        recall_runner=forbidden_legacy,
    )
    final_prompt = payload["agent_prompt_context"]["final_prompt"]
    markers = FIXTURES.joinpath("non_authoritative_markers.txt").read_text(encoding="utf-8").splitlines()

    for marker in markers:
        assert marker in final_prompt
    assert "GOLDEN_RELEVANT_MEMORY" in final_prompt
    assert "OFFTOPIC_SENTINEL" not in final_prompt
    assert "GOLDEN_STALE_MEMORY" not in final_prompt
    assert "GOLDEN_RAW_SHOULD_NOT_APPEAR" not in final_prompt
    assert "GOLDEN_DETAIL_SHOULD_NOT_APPEAR" not in final_prompt
    assert payload["memory_trace"]["engine"] == "tree"
    assert payload["memory_trace"]["reached_final_prompt"] is True
    assert payload["memory_trace"]["raw_included"] is False
