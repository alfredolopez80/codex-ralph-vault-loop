from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.execution_policy import (  # noqa: E402
    ACTIVATION_CONFIG_PATH,
    ExecutionPolicyError,
    PolicyDriftError,
    assert_policy_compatible,
    configured_activation_mode,
    load_execution_policy,
)


EXPECTED_POLICY_SHA = "aa7847050dad0821c83f456b31a42efa0d6eea8989b22b33ecc6edb2c26adbef"


def test_supplied_policy_bytes_and_normalized_budgets_are_exact() -> None:
    path = ROOT / "config" / "execution-policy.toml"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == EXPECTED_POLICY_SHA

    policy = load_execution_policy(path)

    assert policy.version == 4
    assert policy.policy_hash == f"sha256:{EXPECTED_POLICY_SHA}"
    assert policy.full_aristotle_budget == 1
    assert policy.amendment_budget == 1
    assert policy.automatic_children == 0
    assert policy.active_child_max == 1
    assert policy.review_budget_material == 1
    assert policy.total_repair_budget == 3
    assert policy.ordinary_stop_budget == policy.critical_stop_budget == 1


def test_policy_rejects_unknown_key_wrong_type_and_value_drift(tmp_path: Path) -> None:
    source = (ROOT / "config" / "execution-policy.toml").read_text(encoding="utf-8")
    unknown = tmp_path / "unknown.toml"
    unknown.write_text(source + "\nunknown = true\n", encoding="utf-8")
    with pytest.raises(ExecutionPolicyError, match="unknown keys"):
        load_execution_policy(unknown)

    wrong_type = tmp_path / "wrong-type.toml"
    wrong_type.write_text(source.replace("automatic_subagents = 0", "automatic_subagents = false"), encoding="utf-8")
    with pytest.raises(ExecutionPolicyError, match="supplied v4 value"):
        load_execution_policy(wrong_type)

    drift = tmp_path / "drift.toml"
    drift.write_text(source.replace("minimum_tasks = 20", "minimum_tasks = 21"), encoding="utf-8")
    with pytest.raises(ExecutionPolicyError, match="supplied v4 value"):
        load_execution_policy(drift)

    semantically_equal = tmp_path / "semantic-copy.toml"
    semantically_equal.write_text(source + "\n# not part of the supplied bytes\n", encoding="utf-8")
    with pytest.raises(ExecutionPolicyError, match="bytes differ"):
        load_execution_policy(semantically_equal)


def test_active_epoch_blocks_policy_hash_drift() -> None:
    policy = load_execution_policy()
    assert_policy_compatible(policy.policy_hash, policy)
    with pytest.raises(PolicyDriftError, match="active task epoch"):
        assert_policy_compatible("sha256:" + "0" * 64, policy)


def test_activation_mode_is_internal_and_strict() -> None:
    assert configured_activation_mode({}) == "shadow"
    assert configured_activation_mode({"RALPH_CONVERGENT_EXECUTION_MODE": "enforce"}) == "enforce"
    with pytest.raises(ExecutionPolicyError):
        configured_activation_mode({"RALPH_CONVERGENT_EXECUTION_MODE": "maybe"})


def test_repo_local_activation_file_is_plan_and_policy_bound() -> None:
    assert ACTIVATION_CONFIG_PATH.is_file()
    assert configured_activation_mode() == "shadow"


def test_environment_cannot_promote_repo_shadow_to_enforce(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RALPH_CONVERGENT_EXECUTION_MODE", "enforce")
    with pytest.raises(ExecutionPolicyError, match="cannot promote"):
        configured_activation_mode()


def test_environment_cannot_promote_missing_rollout_to_shadow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RALPH_CONVERGENT_EXECUTION_CONFIG", str(tmp_path / "missing.toml"))
    monkeypatch.setenv("RALPH_CONVERGENT_EXECUTION_MODE", "shadow")
    with pytest.raises(ExecutionPolicyError, match="active workspace activation file"):
        configured_activation_mode()


def test_repo_local_activation_file_rejects_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "config" / "convergent-execution-mode.toml"
    path.parent.mkdir()
    path.write_text(
        "version = 1\n"
        "mode = \"shadow\"\n"
        "plan_id = \"wrong\"\n"
        "plan_digest = \"sha256:" + "0" * 64 + "\"\n"
        "policy_hash = \"sha256:" + "0" * 64 + "\"\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("RALPH_CONVERGENT_EXECUTION_MODE", raising=False)
    monkeypatch.setenv("RALPH_CONVERGENT_EXECUTION_CONFIG", str(path))
    with pytest.raises(ExecutionPolicyError, match="plan_id"):
        configured_activation_mode(workspace_root=tmp_path)


def test_activation_override_cannot_point_at_an_unrelated_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "copied-enforce.toml"
    path.write_text((ROOT / "config" / "convergent-execution-mode.toml").read_text(encoding="utf-8").replace('mode = "shadow"', 'mode = "enforce"'), encoding="utf-8")
    monkeypatch.setenv("RALPH_CONVERGENT_EXECUTION_CONFIG", str(path))
    with pytest.raises(ExecutionPolicyError, match="active workspace activation file"):
        configured_activation_mode(workspace_root=ROOT)
