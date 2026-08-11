from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.convergent_contracts import digest_value  # noqa: E402
from shared.convergent_reducer import TransitionRequest  # noqa: E402
from shared.tool_result_attestation import ToolResultAttestationError, request_from_attestation  # noqa: E402


def _attestation() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "task_id": "sha256:" + "1" * 64,
        "task_epoch": "epoch-1",
        "expected_generation": 4,
        "epoch_id": "epoch-1",
        "runtime_attestation_digest": "sha256:" + "2" * 64,
        "tool_use_id": "tool-1",
        "parent_tool_use_id": "",
        "result_stage": "terminal",
        "tool_kind": "validation_gate",
        "tool_name": "pytest",
        "outcome": "pass",
        "relative_paths": ["tests/unit/test_tool_result_attestation.py"],
        "gate": "focused",
        "input_structural_digest": "sha256:" + "3" * 64,
        "result_structural_digest": "sha256:" + "4" * 64,
        "head_digest": "sha256:" + "5" * 64,
        "operation_id": "post-tool-tool-1",
        "operation_digest": "",
        "attestation_digest": "",
    }
    request = TransitionRequest(
        operation_id=str(value["operation_id"]),
        transition="POST_TOOL_RESULT_RECORDED",
        expected_generation=4,
        evidence_ids=("post-tool:tool-1",),
        actor_role="deterministic-runtime",
        evidence_manifest_digest=str(value["result_structural_digest"]),
        reason="tool-result:pass",
        task_id=str(value["task_id"]),
        task_epoch=str(value["task_epoch"]),
        epoch_id=str(value["epoch_id"]),
        head_digest=str(value["head_digest"]),
        runtime_attestation_digest=str(value["runtime_attestation_digest"]),
        tool_use_id=str(value["tool_use_id"]),
        tool_kind=str(value["tool_kind"]),
    )
    value["operation_digest"] = request.operation_digest()
    material = {key: value[key] for key in sorted(value) if key != "attestation_digest"}
    value["attestation_digest"] = digest_value(material)
    return value


def test_structural_attestation_is_bound_to_evidence_only_transition() -> None:
    request, attestation_digest = request_from_attestation(_attestation())
    assert request.transition == "POST_TOOL_RESULT_RECORDED"
    assert request.evidence_manifest_digest == "sha256:" + "4" * 64
    assert attestation_digest.startswith("sha256:")


def test_structural_attestation_rejects_operation_or_result_drift() -> None:
    value = _attestation()
    value["outcome"] = "failure"
    with pytest.raises(ToolResultAttestationError, match="operation digest|attestation digest"):
        request_from_attestation(value)


def test_structural_attestation_rejects_unsupported_tool_kind() -> None:
    value = _attestation()
    value["tool_kind"] = "shell"
    with pytest.raises(ToolResultAttestationError, match="tool_kind"):
        request_from_attestation(value)
