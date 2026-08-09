from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.runtime_profile import (
    CONSERVATIVE_UNKNOWN,
    LUNA,
    SOL,
    classify_model,
    model_provenance_from_payload,
    profile_from_payload,
)


def test_known_model_variants_are_classified_conservatively() -> None:
    assert classify_model("gpt-5.6-luna") == "luna"
    assert classify_model("GPT_5.6_LUNA/max") == "luna"
    assert classify_model("gpt-5.6-sol") == "sol"
    assert classify_model("gpt_5.6_sol/xhigh") == "sol"
    assert classify_model("gpt-5.6-terra") == "terra"
    assert classify_model("") == "unknown"
    assert classify_model("a-model-we-do-not-know") == "unknown"


def test_payload_model_wins_over_environment_and_config(monkeypatch) -> None:
    monkeypatch.delenv("RALPH_SCAFFOLD_PROFILE", raising=False)
    monkeypatch.setenv("RALPH_MODEL", "gpt-5.6-sol")
    profile = profile_from_payload({"model": "gpt-5.6-luna"})
    assert profile.name == LUNA.name
    assert profile.model_family == "luna"
    assert profile.model_source == "payload"
    assert profile.model_verified is True
    assert profile.progress_recovery_bytes == 512
    assert profile.progress_delta_bytes == 256
    assert profile.progress_advisor_budget == 0


def test_fallback_to_repository_config_is_luna(monkeypatch) -> None:
    monkeypatch.delenv("RALPH_SCAFFOLD_PROFILE", raising=False)
    monkeypatch.delenv("RALPH_MODEL", raising=False)
    monkeypatch.delenv("CODEX_MODEL", raising=False)
    profile = profile_from_payload({})
    assert profile.name == LUNA.name
    assert profile.model_family == "luna"
    assert profile.model_source == "repository-default"
    assert profile.model_verified is False
    assert profile.progress_recovery_bytes <= 96
    assert profile.progress_delta_bytes <= 96


def test_valid_override_is_explicit_but_invalid_is_conservative(monkeypatch) -> None:
    monkeypatch.setenv("RALPH_SCAFFOLD_PROFILE", "sol")
    profile = profile_from_payload({"model": "gpt-5.6-luna"})
    assert profile.name == SOL.name
    assert profile.safety_profile == "sol"
    assert profile.model_family == "luna"
    assert profile.model_source == "payload"
    assert profile.model_verified is True
    assert profile.progress_recovery_bytes == 512
    monkeypatch.setenv("RALPH_SCAFFOLD_PROFILE", "not-a-profile")
    profile = profile_from_payload({"model": "gpt-5.6-luna"})
    assert profile.name == CONSERVATIVE_UNKNOWN.name
    assert profile.model_family == "luna"
    assert profile.model_verified is True


def test_unknown_profile_never_relaxes_safety_or_bounds() -> None:
    profile = profile_from_payload({"model": "unknown-model"})
    assert profile.name == "conservative_unknown"
    assert profile.model_family == "unknown"
    assert profile.session_context_bytes_hard <= 2_200
    assert profile.max_stop_continuations == 1
    assert profile.maintenance_mode == "deferred"
    assert profile.progress_recovery_bytes <= 96
    assert profile.progress_advisor_budget == 0


def test_environment_luna_is_verified_for_progress_budget(monkeypatch) -> None:
    monkeypatch.delenv("RALPH_SCAFFOLD_PROFILE", raising=False)
    monkeypatch.setenv("RALPH_MODEL", "gpt-5.6-luna")
    monkeypatch.delenv("CODEX_MODEL", raising=False)
    profile = profile_from_payload({})
    assert profile.model_source == "environment"
    assert profile.model_family == "luna"
    assert profile.model_verified is True
    assert profile.progress_recovery_bytes == 512
    assert profile.progress_delta_bytes == 256


def test_sol_and_unknown_progress_budgets_are_pointer_only(monkeypatch) -> None:
    monkeypatch.delenv("RALPH_SCAFFOLD_PROFILE", raising=False)
    monkeypatch.delenv("RALPH_MODEL", raising=False)
    monkeypatch.delenv("CODEX_MODEL", raising=False)
    sol = profile_from_payload({"model": "gpt-5.6-sol"})
    unknown = profile_from_payload({"model": "provider-custom-model"})
    assert sol.model_source == "payload"
    assert sol.model_verified is True
    assert sol.progress_recovery_bytes <= 96
    assert sol.progress_delta_bytes <= 96
    assert sol.progress_advisor_budget == 0
    assert unknown.model_family == "unknown"
    assert unknown.model_verified is False
    assert unknown.progress_recovery_bytes <= 96
    assert unknown.progress_advisor_budget == 0


def test_model_provenance_serialization_contains_only_safe_fields(monkeypatch) -> None:
    monkeypatch.delenv("RALPH_SCAFFOLD_PROFILE", raising=False)
    provenance = model_provenance_from_payload({"model": "gpt-5.6-luna", "api_key": "redacted"})
    rendered = json.dumps(provenance.as_dict(), sort_keys=True, separators=(",", ":"))
    assert rendered == '{"model_family":"luna","model_source":"payload","model_verified":true}'
    assert "api_key" not in rendered


def test_profile_serialization_is_stable_and_has_no_sensitive_fields() -> None:
    first = json.dumps(SOL.as_dict(), sort_keys=True, separators=(",", ":"))
    second = json.dumps(SOL.as_dict(), sort_keys=True, separators=(",", ":"))
    assert first == second
    assert "api_key" not in first.lower()
    assert "memory_body" not in first
