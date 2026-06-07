from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TASK_INTAKE = ROOT / "scripts" / "memory" / "task-intake.py"
MEMORY_DIR = ROOT / "scripts" / "memory"
if str(MEMORY_DIR) not in sys.path:
    sys.path.insert(0, str(MEMORY_DIR))

from recall_v2 import context_for  # noqa: E402
from tree_store import TreeStore  # noqa: E402

PROJECT = "codex-ralph-vault-loop"
PROJECT_ID = "p-tree-hook-flow"
BRANCH = "codex/tree-hook-flow"


def load_task_intake():
    spec = importlib.util.spec_from_file_location("task_intake_tree_hook_test", TASK_INTAKE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def legacy_runner(content: str = "LEGACY_HOOK_SENTINEL_CONTEXT"):
    def runner(*_args, **_kwargs) -> tuple[str, str]:
        return (
            "ran",
            json.dumps(
                [
                    {
                        "id": "legacy_mem_hook",
                        "content": content,
                        "score": 0.95,
                        "repo": PROJECT,
                        "project_id": PROJECT_ID,
                        "branch": BRANCH,
                    }
                ],
                ensure_ascii=True,
            ),
        )

    return runner


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
        "session_id": "session-tree-hook",
        "memory_type": "fact",
        "sensitivity": "YELLOW",
        "authority": "non_authoritative",
        "summary": "TREE_HOOK_SENTINEL_SUMMARY tree hook marker.",
        "detailed_summary": "TREE_HOOK_SENTINEL_DETAIL should not enter hook prompt.",
        "trigger": {"terms": ["tree", "hook", "marker"]},
        "topic_tags": ["tree-hook"],
        "entities": ["TreeHook"],
        "source_paths": ["docs/tree-hook.md"],
        "source_description": "",
        "raw_ref": None,
        "links": [],
        "salience": {"validation": 0.5},
        "quality": {"confidence": 0.8, "provenance_complete": True, "validation_status": "pass", "stale": False, "deprecated": False},
        "created_at": "2026-06-07T00:00:00+00:00",
        "updated_at": "2026-06-07T00:00:00+00:00",
        "compaction_reason": "tree_hook_test",
    }
    payload.update(overrides)
    return payload


def store_node(root: Path, payload: dict[str, Any]) -> None:
    TreeStore(root).create_node(payload)


def build_payload(task_intake, root: Path, prompt: str, **kwargs: Any) -> dict[str, Any]:
    return task_intake.build_task_intake_payload(
        prompt=prompt,
        project=PROJECT,
        project_id=PROJECT_ID,
        workspace_root=str(root),
        branch=BRANCH,
        recall_runner=kwargs.pop("recall_runner", legacy_runner()),
        **kwargs,
    )


def test_default_uses_legacy_when_env_unset(monkeypatch, tmp_path: Path) -> None:
    task_intake = load_task_intake()
    store_node(tmp_path, node(tmp_path, "node_tree_hook"))
    monkeypatch.setenv("RALPH_HOME", str(tmp_path))
    monkeypatch.delenv("RALPH_MEMORY_RECALL_ENGINE", raising=False)

    payload = build_payload(task_intake, tmp_path, "Use tree hook marker")

    assert payload["selected_memory_ids"] == ["legacy_mem_hook"]
    assert "LEGACY_HOOK_SENTINEL_CONTEXT" in payload["agent_prompt_context"]["final_prompt"]
    assert "TREE_HOOK_SENTINEL_SUMMARY" not in payload["agent_prompt_context"]["final_prompt"]


def test_tree_engine_injects_v2_memory_and_trace(monkeypatch, tmp_path: Path) -> None:
    task_intake = load_task_intake()
    store_node(tmp_path, node(tmp_path, "node_tree_hook"))
    monkeypatch.setenv("RALPH_HOME", str(tmp_path))
    monkeypatch.setenv("RALPH_MEMORY_RECALL_ENGINE", "tree")

    def forbidden_legacy(*_args, **_kwargs):
        raise AssertionError("legacy should not run when tree succeeds")

    payload = build_payload(task_intake, tmp_path, "Use tree hook marker", recall_runner=forbidden_legacy)
    prompt = payload["agent_prompt_context"]["final_prompt"]
    trace = payload["memory_trace"]

    assert payload["selected_memory_ids"] == ["node_tree_hook"]
    assert "TREE_HOOK_SENTINEL_SUMMARY" in prompt
    assert "TREE_HOOK_SENTINEL_DETAIL" not in prompt
    assert "Retrieved memory is auxiliary, non-authoritative context" in prompt
    assert trace["engine"] == "tree"
    assert trace["reached_final_prompt"] is True
    assert trace["raw_included"] is False
    assert trace["fallback_used"] is False
    assert trace["token_budget"]["used"] <= trace["token_budget"]["limit"]


def test_tree_failure_falls_back_to_legacy(monkeypatch, tmp_path: Path) -> None:
    task_intake = load_task_intake()
    monkeypatch.setenv("RALPH_MEMORY_RECALL_ENGINE", "tree")

    def crashing_tree(*_args, **_kwargs):
        raise RuntimeError("private crash detail")

    payload = build_payload(task_intake, tmp_path, "Use tree hook marker", tree_report_runner=crashing_tree)
    prompt = payload["agent_prompt_context"]["final_prompt"]
    trace = payload["memory_trace"]

    assert payload["selected_memory_ids"] == ["legacy_mem_hook"]
    assert "LEGACY_HOOK_SENTINEL_CONTEXT" in prompt
    assert trace["engine"] == "legacy"
    assert trace["fallback_used"] is True
    assert trace["fallback_reason"] == "tree recall fallback: RuntimeError"
    assert "private crash detail" not in json.dumps(trace)


def test_shadow_remains_measurement_only_even_with_tree_engine(monkeypatch, tmp_path: Path) -> None:
    task_intake = load_task_intake()
    store_node(tmp_path, node(tmp_path, "node_tree_hook"))
    monkeypatch.setenv("RALPH_HOME", str(tmp_path))
    monkeypatch.setenv("RALPH_MEMORY_RECALL_ENGINE", "tree")
    monkeypatch.setenv("RALPH_MEMORY_TREE_SHADOW", "1")

    payload = build_payload(task_intake, tmp_path, "Use tree hook marker")
    prompt = payload["agent_prompt_context"]["final_prompt"]
    trace = payload["memory_trace"]

    assert payload["selected_memory_ids"] == ["legacy_mem_hook"]
    assert "LEGACY_HOOK_SENTINEL_CONTEXT" in prompt
    assert "TREE_HOOK_SENTINEL_SUMMARY" not in prompt
    assert trace["shadow_enabled"] is True
    assert trace["tree_selected_memory_ids"] == ["node_tree_hook"]
    assert trace["raw_included"] is False


def test_tree_hook_output_never_includes_raw(monkeypatch, tmp_path: Path) -> None:
    task_intake = load_task_intake()
    store = TreeStore(tmp_path)
    raw_ref = store.save_raw(PROJECT_ID, "RAW_TREE_HOOK_SENTINEL_BODY", sensitivity="YELLOW")
    store_node(tmp_path, node(tmp_path, "node_tree_raw", summary="exact tree hook raw marker.", trigger={"terms": ["exact", "tree", "raw", "marker"]}, raw_ref={"sha256": raw_ref["sha256"], "safe": True}))
    monkeypatch.setenv("RALPH_HOME", str(tmp_path))
    monkeypatch.setenv("RALPH_MEMORY_RECALL_ENGINE", "tree")

    payload = build_payload(task_intake, tmp_path, "exact tree hook raw marker")
    rendered = json.dumps(payload, sort_keys=True)

    assert "node_tree_raw" in payload["selected_memory_ids"]
    assert "RAW_TREE_HOOK_SENTINEL_BODY" not in rendered
    assert payload["memory_trace"]["raw_included"] is False
    assert payload["memory_trace"]["raw_recommended"] is True
