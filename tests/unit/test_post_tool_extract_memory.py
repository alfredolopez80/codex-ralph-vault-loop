from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
HOOK = HOOKS / "post_tool_extract_memory.py"


def load_hook():
    if str(HOOKS) not in sys.path:
        sys.path.insert(0, str(HOOKS))
    spec = importlib.util.spec_from_file_location("post_tool_extract_memory_under_test", HOOK)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_prefilter_skips_context_and_persistence_for_non_candidates(monkeypatch) -> None:
    hook = load_hook()
    monkeypatch.setattr(hook, "is_red", lambda text: "SIMULATED_RED" in text)

    def fail_context(_payload):
        raise AssertionError("active context should not be resolved for rejected candidates")

    def fail_save(*_args, **_kwargs):
        raise AssertionError("learning should not be saved for rejected candidates")

    monkeypatch.setattr(hook, "active_context_from_payload", fail_context)
    monkeypatch.setattr(hook, "save_learning", fail_save)

    for payload in [
        {},
        {"output": "Listed files in the current directory."},
        {"output": "Decision: SIMULATED_RED should not persist."},
    ]:
        monkeypatch.setattr(hook, "read_hook_input", lambda payload=payload: payload)
        assert hook.main() == 0


def test_prefilter_allows_learnable_text_to_reach_context_and_persistence(monkeypatch) -> None:
    hook = load_hook()
    calls: dict[str, object] = {}

    def fake_context(payload):
        calls["context_payload"] = payload
        return object()

    def fake_save(text, **kwargs):
        calls["saved_text"] = text
        calls["save_kwargs"] = kwargs

    payload = {"output": "Decision: keep the shared learning detector for hook memory."}
    monkeypatch.setattr(hook, "read_hook_input", lambda: payload)
    monkeypatch.setattr(hook, "active_context_from_payload", fake_context)
    monkeypatch.setattr(hook, "save_learning", fake_save)

    assert hook.main() == 0
    assert calls["context_payload"] == payload
    assert calls["saved_text"] == payload["output"]
    assert calls["save_kwargs"]["source"] == "PostToolUse"
