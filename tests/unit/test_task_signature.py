from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.active_context import active_context_from_payload
from shared.runtime_profile import LUNA, SOL, profile_from_payload
from shared.task_signature import safe_serialization, signature_from_prompt


def signature(tmp_path: Path, prompt: str, *, branch: str = "main", head: str = "abc", profile=LUNA):
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    context = active_context_from_payload(
        {"cwd": str(workspace), "session_id": "session-a", "branch": branch, "sha": head},
        resolve_git=False,
    )
    return signature_from_prompt(
        prompt,
        context=context,
        profile=profile,
        sensitivity="GREEN",
        checkpoint_identity="checkpoint-a",
    )


def test_signature_is_deterministic_and_contains_no_prompt(tmp_path: Path) -> None:
    prompt = "RAW_PROMPT_SENTINEL implement the cache"
    first = signature(tmp_path, prompt)
    second = signature(tmp_path, prompt)
    assert first == second
    serialized = safe_serialization(first)
    assert prompt not in serialized
    assert "RAW_PROMPT_SENTINEL" not in serialized
    assert first.intent == "implementation"


def test_branch_head_model_and_prompt_invalidate_signature(tmp_path: Path) -> None:
    base = signature(tmp_path, "Implement the cache")
    assert signature(tmp_path, "Implement the cache", branch="feature") != base
    assert signature(tmp_path, "Implement the cache", head="def") != base
    assert signature(tmp_path, "Implement the cache", profile=SOL) != base
    assert signature(tmp_path, "Review the cache") != base


def test_model_provenance_invalidates_context_signature_even_with_same_family(tmp_path: Path) -> None:
    verified = profile_from_payload({"model": "gpt-5.6-luna"})
    unverified = LUNA
    assert verified.model_family == unverified.model_family == "luna"
    assert verified.model_verified is True
    assert unverified.model_verified is False
    assert signature(tmp_path, "Implement the cache", profile=verified) != signature(
        tmp_path, "Implement the cache", profile=unverified
    )


def test_serialization_has_only_metadata_fields(tmp_path: Path) -> None:
    data = json.loads(safe_serialization(signature(tmp_path, "Review safe cache behavior")))
    assert set(data) == {
        "schema_version", "value", "anchor", "project_id", "workspace_instance_id", "branch", "head",
        "prompt_hash", "intent", "sensitivity", "model_family", "checkpoint_identity",
        "model_source", "model_verified",
    }
