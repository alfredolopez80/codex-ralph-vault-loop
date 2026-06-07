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
from tree_store import TreeStore, atomic_write_json  # noqa: E402

PROJECT_SLUG = "codex-ralph-vault-loop"
PROJECT_ID = "p-shadow-mode"
BRANCH = "codex/shadow-mode"


def load_task_intake():
    spec = importlib.util.spec_from_file_location("task_intake_shadow_test", TASK_INTAKE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def legacy_runner(memories: list[dict[str, Any]] | None = None):
    items = memories if memories is not None else [legacy_memory()]

    def runner(*_args, **_kwargs) -> tuple[str, str]:
        return "ran", json.dumps(items, ensure_ascii=True)

    return runner


def legacy_memory() -> dict[str, Any]:
    return {
        "id": "legacy_mem_shadow_001",
        "content": "LEGACY_SHADOW_SENTINEL_CONTEXT",
        "score": 0.95,
        "repo": PROJECT_SLUG,
        "project_id": PROJECT_ID,
        "branch": BRANCH,
    }


def node(root: Path, node_id: str, **overrides: Any) -> dict[str, Any]:
    context = context_for(root, PROJECT_ID, BRANCH)
    payload = {
        "schema_version": "ralph_memory_node_v2",
        "node_id": node_id,
        "project_id": PROJECT_ID,
        "workspace_instance_id": context.workspace_instance_id,
        "repo_remote_hash": "remotehash",
        "branch": BRANCH,
        "commit": "abc123",
        "session_id": "session-shadow",
        "memory_type": "fact",
        "sensitivity": "YELLOW",
        "authority": "non_authoritative",
        "summary": "Shadow mode marker for tree comparison.",
        "detailed_summary": "Shadow mode marker detail for comparison only.",
        "trigger": {"terms": ["shadow-mode-marker"]},
        "topic_tags": ["shadow"],
        "entities": ["ShadowMode"],
        "source_paths": ["docs/shadow-mode.md"],
        "source_description": "",
        "raw_ref": None,
        "links": [],
        "salience": {"validation": 0.5},
        "quality": {"confidence": 0.8, "provenance_complete": True, "stale": False, "deprecated": False},
        "created_at": "2026-06-07T00:00:00+00:00",
        "updated_at": "2026-06-07T00:00:00+00:00",
        "compaction_reason": "shadow_test",
    }
    payload.update(overrides)
    return payload


def store_node(root: Path, payload: dict[str, Any]) -> None:
    TreeStore(root).create_node(payload)


def write_direct(root: Path, payload: dict[str, Any]) -> None:
    store = TreeStore(root)
    store.ensure_layout(PROJECT_ID)
    atomic_write_json(store.node_path(PROJECT_ID, payload["node_id"]), payload)


def payload(task_intake, root: Path, prompt: str, **kwargs: Any) -> dict[str, Any]:
    return task_intake.build_task_intake_payload(
        prompt=prompt,
        project=PROJECT_SLUG,
        project_id=PROJECT_ID,
        workspace_root=str(root),
        branch=BRANCH,
        recall_runner=kwargs.pop("recall_runner", legacy_runner()),
        **kwargs,
    )


def test_shadow_mode_does_not_alter_final_prompt(monkeypatch, tmp_path: Path) -> None:
    task_intake = load_task_intake()
    store_node(tmp_path, node(tmp_path, "node_tree_shadow"))
    monkeypatch.setenv("RALPH_HOME", str(tmp_path))
    monkeypatch.delenv("RALPH_MEMORY_TREE_SHADOW", raising=False)
    base = payload(task_intake, tmp_path, "Compare shadow mode marker")
    monkeypatch.setenv("RALPH_MEMORY_TREE_SHADOW", "1")

    shadow = payload(task_intake, tmp_path, "Compare shadow mode marker")

    assert shadow["agent_prompt_context"]["final_prompt"] == base["agent_prompt_context"]["final_prompt"]
    assert shadow["selected_memory_context"] == base["selected_memory_context"]
    assert shadow["selected_memory_ids"] == ["legacy_mem_shadow_001"]
    assert shadow["memory_trace"]["shadow_enabled"] is True
    assert shadow["memory_trace"]["tree_selected_memory_ids"] == ["node_tree_shadow"]


def test_shadow_trace_renders_public_comparison(monkeypatch, tmp_path: Path) -> None:
    task_intake = load_task_intake()
    store_node(tmp_path, node(tmp_path, "node_tree_shadow"))
    monkeypatch.setenv("RALPH_HOME", str(tmp_path))
    monkeypatch.setenv("RALPH_MEMORY_TREE_SHADOW", "1")
    monkeypatch.setenv("RALPH_MEMORY_TRACE", "1")
    result = payload(task_intake, tmp_path, "Compare shadow mode marker")

    rendered = task_intake.render_markdown(result)
    trace_line = next(line for line in rendered.splitlines() if line.startswith("MEMORY_TRACE_JSON="))
    trace = json.loads(trace_line.removeprefix("MEMORY_TRACE_JSON="))

    assert trace["shadow_enabled"] is True
    assert trace["legacy_selected_memory_ids"] == ["legacy_mem_shadow_001"]
    assert trace["tree_selected_memory_ids"] == ["node_tree_shadow"]
    assert trace["tree_raw_recommended"] is False
    assert trace["raw_included"] is False
    assert "Shadow mode marker detail" not in trace_line


def test_v2_crash_in_shadow_mode_falls_back_silently_to_legacy(monkeypatch, tmp_path: Path) -> None:
    task_intake = load_task_intake()
    monkeypatch.setenv("RALPH_MEMORY_TREE_SHADOW", "1")

    def crashing_tree(*_args, **_kwargs):
        raise RuntimeError("tree crash detail")

    result = payload(task_intake, tmp_path, "Compare shadow mode marker", tree_recall_runner=crashing_tree)
    trace = result["memory_trace"]

    assert "LEGACY_SHADOW_SENTINEL_CONTEXT" in result["agent_prompt_context"]["final_prompt"]
    assert trace["tree_would_have_failed"] is True
    assert trace["tree_selected_memory_ids"] == []
    assert trace["raw_included"] is False
    assert "tree crash detail" not in json.dumps(trace)


def test_red_prompt_produces_no_unsafe_tree_output(monkeypatch, tmp_path: Path) -> None:
    task_intake = load_task_intake()
    monkeypatch.setenv("RALPH_HOME", str(tmp_path))
    monkeypatch.setenv("RALPH_MEMORY_TREE_SHADOW", "1")
    red_prompt = "Inspect " + "api" + "_key=abcd1234"

    result = payload(task_intake, tmp_path, red_prompt, recall_runner=legacy_runner([]))
    trace = result["memory_trace"]

    assert result["sensitivity"] == "RED"
    assert trace["tree_selected_memory_ids"] == []
    assert trace["tree_rejected_reasons"] == [{"id": "prompt", "reason": "red_prompt"}]
    assert trace["raw_included"] is False
    assert red_prompt not in json.dumps(trace)


def test_wrong_scope_rejections_appear_in_tree_trace(monkeypatch, tmp_path: Path) -> None:
    task_intake = load_task_intake()
    monkeypatch.setenv("RALPH_HOME", str(tmp_path))
    monkeypatch.setenv("RALPH_MEMORY_TREE_SHADOW", "1")
    write_direct(tmp_path, node(tmp_path, "node_wrong_project", project_id="p-other", summary="scope marker"))
    write_direct(tmp_path, node(tmp_path, "node_wrong_branch", branch="other-branch", summary="scope marker"))

    result = payload(task_intake, tmp_path, "Inspect scope marker", recall_runner=legacy_runner([]))
    reasons = {item["id"]: item["reason"] for item in result["memory_trace"]["tree_rejected_reasons"]}

    assert reasons["node_wrong_project"] == "wrong_project"
    assert reasons["node_wrong_branch"] == "wrong_branch"
    assert result["agent_prompt_context"]["final_prompt"] == "Inspect scope marker"


def test_legacy_default_unchanged_when_shadow_env_unset(monkeypatch, tmp_path: Path) -> None:
    task_intake = load_task_intake()
    monkeypatch.delenv("RALPH_MEMORY_TREE_SHADOW", raising=False)

    def forbidden_tree(*_args, **_kwargs):
        raise AssertionError("tree recall should not run")

    result = payload(task_intake, tmp_path, "Compare shadow mode marker", tree_recall_runner=forbidden_tree)

    assert result["selected_memory_ids"] == ["legacy_mem_shadow_001"]
    assert "shadow_enabled" not in result["memory_trace"]
    assert result["agent_prompt_context"]["final_prompt"].count("LEGACY_SHADOW_SENTINEL_CONTEXT") == 1
