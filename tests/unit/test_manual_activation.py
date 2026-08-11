from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.execution_policy import load_execution_policy  # noqa: E402
from shared.manual_activation import (  # noqa: E402
    MANUAL_ACTIVATION_RELATIVE_PATH,
    ManualActivationError,
    load_manual_activation,
    manual_activation_payload,
)


def _toml(material: dict[str, object]) -> str:
    lines: list[str] = []
    for key, value in material.items():
        if isinstance(value, list):
            lines.append(f'{key} = [' + ", ".join(f'"{item}"' for item in value) + "]")
        elif isinstance(value, int):
            lines.append(f"{key} = {value}")
        else:
            lines.append(f'{key} = "{value}"')
    return "\n".join(lines) + "\n"


def _write_activation(tmp_path: Path, *, head: str = "a" * 40) -> None:
    policy = load_execution_policy()
    material = manual_activation_payload(
        workspace_root=tmp_path,
        branch="main",
        head_sha=head,
        tools=("bash", "git", "python3"),
        policy=policy,
        approval_id="test-manual-enforce",
    )
    target = tmp_path / MANUAL_ACTIVATION_RELATIVE_PATH
    target.parent.mkdir(parents=True)
    target.write_text(_toml(material), encoding="utf-8")


def test_manual_activation_round_trips_and_binds_checkout(tmp_path: Path) -> None:
    _write_activation(tmp_path)
    activation = load_manual_activation(
        tmp_path,
        branch="main",
        head_sha="a" * 40,
        policy=load_execution_policy(),
    )
    assert activation.branch == "main"
    assert activation.tools == ("bash", "git", "python3")
    assert activation.attestation_digest.startswith("sha256:")
    assert activation.lease_evidence(cwd=str(tmp_path), branch="main", task_epoch="epoch-1").source == "manual-approval"


def test_manual_activation_rejects_head_or_scope_drift(tmp_path: Path) -> None:
    _write_activation(tmp_path)
    with pytest.raises(ManualActivationError, match="HEAD binding"):
        load_manual_activation(tmp_path, branch="main", head_sha="b" * 40, policy=load_execution_policy())
    path = tmp_path / MANUAL_ACTIVATION_RELATIVE_PATH
    content = path.read_text(encoding="utf-8").replace('approval_scope = "global-enforce"', 'approval_scope = "shadow"')
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ManualActivationError, match="digest|scope"):
        load_manual_activation(tmp_path, branch="main", head_sha="a" * 40, policy=load_execution_policy())
