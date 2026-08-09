from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.runtime_profile import CONSERVATIVE_UNKNOWN, LUNA, SOL, classify_model, profile_from_payload


def test_known_model_variants_are_classified_conservatively() -> None:
    assert classify_model("gpt-5.6-luna") == "luna"
    assert classify_model("GPT_5.6_LUNA/max") == "luna"
    assert classify_model("gpt-5.6-sol") == "sol"
    assert classify_model("gpt_5.6_sol/xhigh") == "sol"
    assert classify_model("") == "unknown"
    assert classify_model("a-model-we-do-not-know") == "unknown"


def test_payload_model_wins_over_environment_and_config(monkeypatch) -> None:
    monkeypatch.delenv("RALPH_SCAFFOLD_PROFILE", raising=False)
    monkeypatch.setenv("RALPH_MODEL", "gpt-5.6-sol")
    assert profile_from_payload({"model": "gpt-5.6-luna"}) == LUNA


def test_fallback_to_repository_config_is_luna(monkeypatch) -> None:
    monkeypatch.delenv("RALPH_SCAFFOLD_PROFILE", raising=False)
    monkeypatch.delenv("RALPH_MODEL", raising=False)
    monkeypatch.delenv("CODEX_MODEL", raising=False)
    assert profile_from_payload({}) == LUNA


def test_valid_override_is_explicit_but_invalid_is_conservative(monkeypatch) -> None:
    monkeypatch.setenv("RALPH_SCAFFOLD_PROFILE", "sol")
    assert profile_from_payload({"model": "gpt-5.6-luna"}) == SOL
    monkeypatch.setenv("RALPH_SCAFFOLD_PROFILE", "not-a-profile")
    assert profile_from_payload({"model": "gpt-5.6-luna"}) == CONSERVATIVE_UNKNOWN


def test_unknown_profile_never_relaxes_safety_or_bounds() -> None:
    profile = profile_from_payload({"model": "unknown-model"})
    assert profile.name == "conservative_unknown"
    assert profile.model_family == "unknown"
    assert profile.session_context_bytes_hard <= 2_200
    assert profile.max_stop_continuations == 1
    assert profile.maintenance_mode == "deferred"


def test_profile_serialization_is_stable_and_has_no_sensitive_fields() -> None:
    first = json.dumps(SOL.as_dict(), sort_keys=True, separators=(",", ":"))
    second = json.dumps(SOL.as_dict(), sort_keys=True, separators=(",", ":"))
    assert first == second
    assert "api_key" not in first.lower()
    assert "memory_body" not in first
