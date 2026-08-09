from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
SCRIPT = HOOKS / "user_prompt_dispatch.py"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

import user_prompt_dispatch as dispatcher
from shared.context_delta import cache_path
from shared.prompt_context_components import run_intake
from shared.runtime_profile import LUNA


def payload(tmp_path: Path, *, model: str = "gpt-5.6-luna", prompt: str = "Implement bounded prompt caching") -> dict:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    return {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "session-a",
        "turn_id": "turn-a",
        "cwd": str(workspace),
        "branch": "main",
        "sha": "abc123",
        "model": model,
        "prompt": prompt,
    }


def configure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    monkeypatch.setenv("CODEX_MEMORY_HOME", str(tmp_path / "empty-memory"))
    monkeypatch.setenv("VAULT_DIR", str(tmp_path / "empty-vault"))
    monkeypatch.setenv("RALPH_LOCAL_NOTES_ROOTS", "")
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setattr(
        dispatcher,
        "run_intake",
        lambda _prompt, _context, _profile: (
            "# Ralph Task Intake\nrecall_status=ran\nselected_memory_ids=memory-sentinel",
            ["memory-sentinel"],
            "no",
        ),
    )
    state = {
        "routing": {"subagent_route": "none", "policy_version": "fixture"},
        "consultation_eligible": False,
    }
    monkeypatch.setattr(dispatcher, "initialize", lambda _payload: dict(state))
    monkeypatch.setattr(dispatcher, "read_state", lambda _payload: dict(state))


def context_from_output(output: str) -> str:
    decoded = json.loads(output)
    return decoded["hookSpecificOutput"]["additionalContext"]


def test_first_prompt_emits_one_bounded_package_and_repeat_is_silent(monkeypatch, tmp_path: Path) -> None:
    configure(monkeypatch, tmp_path)
    event = payload(tmp_path, prompt="RAW_PROMPT_SENTINEL implement bounded caching")
    first = dispatcher.run(event)
    assert first.count("\n") == 0
    context = context_from_output(first)
    assert "Ralph Task Intake" in context
    assert "Prompt classification:" in context
    assert len(context.encode("utf-8")) <= 1_800
    assert dispatcher.run(event) == ""
    active = dispatcher.active_context_from_payload(event, resolve_git=False)
    cached = cache_path(active).read_text(encoding="utf-8")
    assert "RAW_PROMPT_SENTINEL" not in cached
    assert "memory-sentinel" in cached


def test_branch_head_model_and_memory_generation_invalidate(monkeypatch, tmp_path: Path) -> None:
    configure(monkeypatch, tmp_path)
    event = payload(tmp_path)
    assert dispatcher.run(event)
    assert dispatcher.run(event) == ""
    assert dispatcher.run({**event, "branch": "feature"})
    assert dispatcher.run({**event, "sha": "def456"})
    assert dispatcher.run({**event, "model": "gpt-5.6-sol"})
    assert dispatcher.run({**event, "memory_generation": "generation-b"})


def test_sol_context_uses_delta_profile_and_omits_prompt_improvement(monkeypatch, tmp_path: Path) -> None:
    configure(monkeypatch, tmp_path)
    output = dispatcher.run(payload(tmp_path, model="gpt-5.6-sol"))
    context = context_from_output(output)
    assert len(context.encode("utf-8")) <= 800
    assert "Prompt contract: preserve task type" not in context


def test_sensitive_prompt_blocks_before_cache_or_recall(monkeypatch, tmp_path: Path) -> None:
    configure(monkeypatch, tmp_path)
    calls = {"intake": 0}

    def intake(*_args):
        calls["intake"] += 1
        return "", [], "unknown"

    monkeypatch.setattr(dispatcher, "run_intake", intake)
    event = payload(tmp_path, prompt="token" + "=fixture-value")
    output = json.loads(dispatcher.run(event))
    assert output["decision"] == "block"
    assert calls["intake"] == 0
    active = dispatcher.active_context_from_payload(event, resolve_git=False)
    assert not cache_path(active).exists()


def test_recall_timeout_has_explicit_local_fallback(monkeypatch, tmp_path: Path) -> None:
    context = dispatcher.active_context_from_payload(payload(tmp_path), resolve_git=False)
    module = SimpleNamespace(
        build_task_intake_payload=lambda **_kwargs: (_ for _ in ()).throw(TimeoutError("fixture")),
        render_markdown=lambda _value: "unreachable",
    )
    monkeypatch.setattr("shared.prompt_context_components._load_task_intake", lambda: module)
    rendered, selected, clarification = run_intake("Implement bounded caching", context, LUNA)
    assert "recall_status=failed" in rendered
    assert "memory_fallback=recall_timeout" in rendered
    assert selected == []
    assert clarification == "unknown"


def test_invalid_or_empty_payload_is_clean_and_silent(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.update(
        {
            "RALPH_HOME": str(tmp_path / "ralph"),
            "CODEX_MEMORY_HOME": str(tmp_path / "empty-memory"),
            "RALPH_LOCAL_NOTES_ROOTS": "",
        }
    )
    for raw in ("", "[broken", "[]", "{}"):
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=ROOT,
            input=raw,
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        assert result.returncode == 0
        assert result.stdout == ""
