from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_DIR = REPO_ROOT / ".codex" / "hooks"
TASK_INTAKE = REPO_ROOT / "scripts" / "memory" / "task-intake.py"
USER_PROMPT_CAPTURE = HOOK_DIR / "user_prompt_capture.py"


def load_module(name: str, path: Path, extra_path: Path | None = None):
    if extra_path is not None and str(extra_path) not in sys.path:
        sys.path.insert(0, str(extra_path))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def option_value(args: list[str], option: str) -> str:
    return args[args.index(option) + 1]


def test_memory_recall_flow_injects_selected_memory_before_fake_agent(monkeypatch, capsys) -> None:
    task_intake = load_module("task_intake_e2e", TASK_INTAKE)
    user_prompt_capture = load_module("user_prompt_capture_e2e", USER_PROMPT_CAPTURE, HOOK_DIR)

    current_branch = "codex/e2e-memory-flow"
    prompt = "Build context with Ralph recall memory for the final fake agent call"
    events: list[str] = []
    recall_calls: list[dict[str, object]] = []
    fake_agent_calls: list[dict[str, object]] = []

    def fake_recall_runner(
        query: str,
        project: str,
        limit: int,
        project_id: str = "",
        workspace_root: str = "",
        phase: str = "",
    ) -> tuple[str, str]:
        events.append("recall:start")
        recall_calls.append(
            {
                "phase": phase,
                "query": query,
                "project": project,
                "limit": limit,
                "project_id": project_id,
                "workspace_root": workspace_root,
            }
        )
        result = (
            "ran",
            json.dumps(
                [
                    {
                        "id": "mem_e2e_relevant_001",
                        "content": "RALPH_E2E_SENTINEL_RELEVANT_MEMORY",
                        "score": 0.95,
                        "repo": "codex-ralph-vault-loop",
                        "branch": current_branch,
                    },
                    {
                        "id": "mem_e2e_irrelevant_001",
                        "content": "RALPH_E2E_SENTINEL_IRRELEVANT_MEMORY",
                        "score": 0.10,
                        "repo": "other-repo",
                    },
                ],
                ensure_ascii=True,
            ),
        )
        events.append("recall:end")
        return result

    def fake_agent_run(agent_prompt_context: dict[str, object]) -> dict[str, object]:
        events.append("agent.run")
        fake_agent_calls.append(agent_prompt_context)
        agent_prompt_context["memory_trace"]["selected_memory_ids"].append("mutated_after_agent")
        return {"status": "ok", "received_context": agent_prompt_context}

    def fake_subprocess_run(args, input, text, capture_output, check, timeout, env):
        assert text is True
        assert capture_output is True
        assert check is False
        assert timeout == user_prompt_capture.TASK_INTAKE_TIMEOUT_SECONDS
        assert env["RALPH_BRANCH"] == current_branch
        assert option_value(args, "--project") == "codex-ralph-vault-loop"
        assert option_value(args, "--branch") == current_branch

        hook_payload = json.loads(input)
        payload = task_intake.build_task_intake_payload(
            prompt=hook_payload["prompt"],
            project=option_value(args, "--project"),
            project_id=option_value(args, "--project-id"),
            workspace_root=option_value(args, "--workspace-root"),
            branch=option_value(args, "--branch"),
            recall_runner=fake_recall_runner,
        )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(user_prompt_capture.subprocess, "run", fake_subprocess_run)

    context = user_prompt_capture.ActiveContext(
        ralph_code_root=REPO_ROOT,
        workspace_root=REPO_ROOT,
        git_root=REPO_ROOT,
        durable_root=None,
        project_slug="codex-ralph-vault-loop",
        project_id="p-e2e-memory-flow",
        remote_url_hash="",
        branch=current_branch,
        sha="testsha",
        session_id="session-e2e",
        workspace_instance_id="workspace-e2e",
    )

    user_prompt_capture.run_task_intake({"prompt": prompt, "cwd": str(REPO_ROOT)}, context)
    hook_output = capsys.readouterr().out.strip()
    payload = json.loads(hook_output)
    agent_result = fake_agent_run(payload["agent_prompt_context"])
    final_prompt = agent_result["received_context"]["final_prompt"]
    trace = payload["memory_trace"]

    assert [call["phase"] for call in recall_calls] == ["before_context"]
    assert events == ["recall:start", "recall:end", "agent.run"]
    assert recall_calls[0]["project"] == "codex-ralph-vault-loop"
    assert current_branch in str(recall_calls[0]["query"])

    assert payload["selected_memory_ids"] == ["mem_e2e_relevant_001"]
    assert "mem_e2e_relevant_001" in trace["selected_memory_ids"]
    assert "mem_e2e_irrelevant_001" not in payload["selected_memory_ids"]
    assert "mem_e2e_irrelevant_001" not in trace["selected_memory_ids"]

    assert "RALPH_E2E_SENTINEL_RELEVANT_MEMORY" in final_prompt
    assert "RALPH_E2E_SENTINEL_IRRELEVANT_MEMORY" not in final_prompt
    assert fake_agent_calls[0]["final_prompt"] == payload["agent_prompt_context"]["final_prompt"]

    assert trace["recall_count"] == 2
    assert trace["selected_count"] == 1
    assert trace["selected_memory_ids"] == ["mem_e2e_relevant_001"]
    assert trace["injected_token_count"] > 0
    assert payload["memory_trace"]["selected_memory_ids"] == ["mem_e2e_relevant_001"]


def test_recall_timeout_fallback_completes_before_fake_agent() -> None:
    task_intake = load_module("task_intake_timeout_e2e", TASK_INTAKE)
    events: list[str] = []

    def timeout_recall_runner(
        query: str,
        project: str,
        limit: int,
        project_id: str = "",
        workspace_root: str = "",
        phase: str = "",
    ) -> tuple[str, str]:
        events.append("recall:start")
        assert phase == "before_context"
        assert "codex-ralph-vault-loop" in query
        events.append("recall:fallback")
        return "failed", "recall timeout after 10s"

    def fake_agent_run(agent_prompt_context: dict[str, object]) -> dict[str, object]:
        events.append("agent.run")
        assert agent_prompt_context["memory_status"] == "fallback_no_recall"
        assert agent_prompt_context["memory_trace"]["memory_status"] == "fallback_no_recall"
        assert agent_prompt_context["memory_trace"]["fallback_reason"] == "recall timeout after 10s"
        return {"status": "ok"}

    payload = task_intake.build_task_intake_payload(
        prompt="Build context with Ralph recall memory before the fake agent call",
        project="codex-ralph-vault-loop",
        project_id="p-e2e-timeout",
        workspace_root=str(REPO_ROOT),
        branch="codex/e2e-memory-timeout",
        recall_runner=timeout_recall_runner,
    )
    fake_agent_run(payload["agent_prompt_context"])

    assert events == ["recall:start", "recall:fallback", "agent.run"]
    assert payload["memory_status"] == "fallback_no_recall"
    assert payload["selected_memory_ids"] == []
    assert payload["memory_trace"]["recall_count"] == 0
    assert payload["memory_trace"]["selected_count"] == 0
