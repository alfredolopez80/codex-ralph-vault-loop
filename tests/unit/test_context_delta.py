from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.active_context import active_context_from_payload
from shared.context_delta import cache_path, claim, finalize
from shared.runtime_profile import LUNA
from shared.task_signature import signature_from_prompt


def fixture(tmp_path: Path, prompt: str = "Implement safe prompt caching"):
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    context = active_context_from_payload(
        {"cwd": str(workspace), "session_id": "session-a", "branch": "main", "sha": "abc"},
        resolve_git=False,
    )
    signature = signature_from_prompt(
        prompt, context=context, profile=LUNA, sensitivity="GREEN", checkpoint_identity="checkpoint-a"
    )
    return context, signature


def kwargs(**overrides: str):
    base = {
        "memory_generation": "generation-a",
        "route": "local",
        "profile": "luna",
        "clarification_state": "clear",
        "checkpoint_hash": "checkpoint-a",
    }
    base.update(overrides)
    return base


def test_same_fingerprint_hits_and_preserves_selected_ids(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    context, signature = fixture(tmp_path)
    assert claim(context, signature, **kwargs()).status == "miss"
    assert finalize(context, signature, selected_memory_ids=["memory-sentinel"], **kwargs())
    hit = claim(context, signature, **kwargs())
    assert hit.status == "hit"
    assert hit.selected_memory_ids == ("memory-sentinel",)


def test_generation_change_is_a_miss(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    context, signature = fixture(tmp_path)
    assert claim(context, signature, **kwargs()).status == "miss"
    assert finalize(context, signature, selected_memory_ids=[], **kwargs())
    assert claim(context, signature, **kwargs(memory_generation="generation-b")).status == "miss"


def test_corrupt_cache_is_quarantined_and_recovers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    context, signature = fixture(tmp_path)
    path = cache_path(context)
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    assert claim(context, signature, **kwargs()).status == "miss"
    assert list(path.parent.glob("cache.invalid.*.json"))


def test_symlink_runtime_fails_open_without_escape(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "runtime"
    link.symlink_to(target, target_is_directory=True)
    monkeypatch.setenv("RALPH_HOME", str(link))
    context, signature = fixture(tmp_path)
    assert claim(context, signature, **kwargs()).status == "unavailable"
    assert not list(target.rglob("cache.json"))


def test_cache_contains_no_raw_prompt_and_is_bounded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    monkeypatch.setenv("RALPH_CONTEXT_CACHE_MAX_ENTRIES", "2")
    context, signature = fixture(tmp_path, "RAW_PROMPT_SENTINEL implement caching")
    assert claim(context, signature, **kwargs()).status == "miss"
    assert finalize(context, signature, selected_memory_ids=["memory-id"], **kwargs())
    for index in range(3):
        _, current = fixture(tmp_path, f"Implement cache variant {index}")
        claim(context, current, **kwargs())
        finalize(context, current, selected_memory_ids=[], **kwargs())
        time.sleep(0.002)
    text = cache_path(context).read_text(encoding="utf-8")
    assert "RAW_PROMPT_SENTINEL" not in text
    assert len(json.loads(text)["entries"]) <= 2


def test_ttl_expiry_causes_miss(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    monkeypatch.setenv("RALPH_CONTEXT_CACHE_TTL_SECONDS", "1")
    context, signature = fixture(tmp_path)
    claim(context, signature, **kwargs())
    finalize(context, signature, selected_memory_ids=[], **kwargs())
    path = cache_path(context)
    state = json.loads(path.read_text(encoding="utf-8"))
    for entry in state["entries"].values():
        entry["updated_epoch"] = time.time() - 5
    path.write_text(json.dumps(state), encoding="utf-8")
    assert claim(context, signature, **kwargs()).status == "miss"
