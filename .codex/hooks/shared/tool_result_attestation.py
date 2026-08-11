"""Closed, content-safe PostTool transition attestation contract."""
from __future__ import annotations

import math
from typing import Any, Mapping

from .convergent_contracts import SHA256_RE, digest_value
from .convergent_reducer import TransitionRequest


class ToolResultAttestationError(ValueError):
    """Raised when a PostTool transition is not independently bounded."""


ALLOWED_TRANSITIONS = frozenset(
    {
        # PostTool is an evidence boundary only.  It never advances the
        # lifecycle, closes obligations, invokes review, or consumes a
        # repair/Stop budget.
        "POST_TOOL_RESULT_RECORDED",
    }
)
_RESULT_FIELDS = frozenset({"tool_name", "success", "exit_code", "status", "stdout_digest", "stderr_digest"})
_V1_FIELDS = frozenset(
    {
        "schema_version",
        "task_id",
        "task_epoch",
        "expected_generation",
        "epoch_id",
        "runtime_attestation_digest",
        "tool_use_id",
        "parent_tool_use_id",
        "result_stage",
        "tool_kind",
        "tool_name",
        "outcome",
        "relative_paths",
        "gate",
        "input_structural_digest",
        "result_structural_digest",
        "head_digest",
        "operation_id",
        "operation_digest",
        "attestation_digest",
    }
)
_LEGACY_REQUEST_FIELDS = frozenset(
    {
        "operation_id",
        "transition",
        "expected_generation",
        "evidence_ids",
        "obligation_closures",
        "finding_closures",
        "accepted_finding_ids",
        "actor_role",
        "tier",
        "risk",
        "decision_fingerprint",
        "decision_version",
        "amendment_fingerprint",
        "approval_fingerprint",
        "evidence_manifest_digest",
        "findings_digest",
        "final_audit_digest",
        "failure_fingerprint",
        "audit_pass",
        "hard_gates_pass",
        "reason",
        "handoff_digest",
    }
)


_EVENT_BINDING_FIELDS = frozenset(
    {
        "tool_use_id",
        "parent_tool_use_id",
        "result_stage",
        "tool_kind",
        "tool_name",
        "outcome",
        "input_structural_digest",
        "result_structural_digest",
    }
)


def request_from_attestation(
    value: object,
    *,
    event_binding: Mapping[str, object] | None = None,
) -> tuple[TransitionRequest, str]:
    if not isinstance(value, Mapping):
        raise ToolResultAttestationError("PostTool transition attestation must be an object")
    # The v1 structural contract is the only production contract.  The
    # bounded legacy shape is retained solely for fixtures that predate the
    # contract; it is normalized into the same evidence-only transition and
    # still requires a runtime attestation digest and result digest.
    if "schema_version" in value:
        return _request_from_v1(value, event_binding=event_binding)
    if event_binding is not None:
        raise ToolResultAttestationError("PostTool production attestation must use the v1 event-bound contract")
    if set(value) - (_LEGACY_REQUEST_FIELDS | {"result", "result_digest", "attestation_digest"}):
        raise ToolResultAttestationError("PostTool transition attestation has unknown fields")
    transition = value.get("transition")
    operation_id = value.get("operation_id")
    expected_generation = value.get("expected_generation")
    if transition == "EVIDENCE_RECORDED":
        transition = "POST_TOOL_RESULT_RECORDED"
    if not isinstance(transition, str) or transition not in ALLOWED_TRANSITIONS:
        raise ToolResultAttestationError("PostTool transition is not in the closed allowlist")
    if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 180:
        raise ToolResultAttestationError("PostTool operation_id is invalid")
    if isinstance(expected_generation, bool) or not isinstance(expected_generation, int) or expected_generation < 0:
        raise ToolResultAttestationError("PostTool expected_generation is invalid")
    result = value.get("result")
    if not isinstance(result, Mapping) or set(result) != _RESULT_FIELDS:
        raise ToolResultAttestationError("PostTool result evidence is incomplete")
    for field in ("stdout_digest", "stderr_digest"):
        if not isinstance(result.get(field), str) or not SHA256_RE.fullmatch(result[field]):
            raise ToolResultAttestationError(f"PostTool {field} is invalid")
    if not isinstance(result.get("tool_name"), str) or not result["tool_name"] or len(result["tool_name"]) > 180:
        raise ToolResultAttestationError("PostTool tool_name is invalid")
    if not isinstance(result.get("success"), bool):
        raise ToolResultAttestationError("PostTool success must be boolean")
    if not isinstance(result.get("status"), str) or not result["status"] or len(result["status"]) > 64:
        raise ToolResultAttestationError("PostTool status is invalid")
    exit_code = result.get("exit_code")
    if exit_code is not None and (isinstance(exit_code, bool) or not isinstance(exit_code, int) or abs(exit_code) > 255):
        raise ToolResultAttestationError("PostTool exit_code is invalid")
    result_digest = digest_value(dict(result))
    expected_result_digest = value.get("result_digest")
    if expected_result_digest != result_digest:
        raise ToolResultAttestationError("PostTool result digest is not bound")
    evidence_ids = _bounded_strings(value.get("evidence_ids", ()), "evidence_ids")
    obligation_closures = _bounded_strings(value.get("obligation_closures", ()), "obligation_closures")
    finding_closures = _bounded_strings(value.get("finding_closures", ()), "finding_closures")
    accepted_finding_ids = _bounded_strings(value.get("accepted_finding_ids", ()), "accepted_finding_ids")
    attestation_digest = value.get("attestation_digest")
    if not isinstance(attestation_digest, str) or not SHA256_RE.fullmatch(attestation_digest):
        raise ToolResultAttestationError("PostTool runtime attestation digest is invalid")
    request = TransitionRequest(
        operation_id=operation_id,
        transition=transition,
        expected_generation=expected_generation,
        evidence_ids=evidence_ids,
        obligation_closures=obligation_closures,
        finding_closures=finding_closures,
        accepted_finding_ids=accepted_finding_ids,
        actor_role=str(value.get("actor_role") or "deterministic-runtime"),
        tier=str(value.get("tier") or ""),
        risk=str(value.get("risk") or "low"),
        decision_fingerprint=str(value.get("decision_fingerprint") or ""),
        decision_version=int(value.get("decision_version") or 0),
        amendment_fingerprint=str(value.get("amendment_fingerprint") or ""),
        approval_fingerprint=str(value.get("approval_fingerprint") or ""),
        evidence_manifest_digest=str(value.get("evidence_manifest_digest") or ""),
        findings_digest=str(value.get("findings_digest") or ""),
        final_audit_digest=str(value.get("final_audit_digest") or ""),
        failure_fingerprint=str(value.get("failure_fingerprint") or ""),
        audit_pass=value.get("audit_pass") if isinstance(value.get("audit_pass"), bool) else None,
        hard_gates_pass=value.get("hard_gates_pass") if isinstance(value.get("hard_gates_pass"), bool) else None,
        reason=str(value.get("reason") or "")[:512],
        handoff_digest=str(value.get("handoff_digest") or ""),
        attestation_digest=attestation_digest,
    )
    return request, attestation_digest


def _request_from_v1(
    value: Mapping[str, object],
    *,
    event_binding: Mapping[str, object] | None,
) -> tuple[TransitionRequest, str]:
    if set(value) != _V1_FIELDS:
        raise ToolResultAttestationError("PostTool v1 attestation has unknown or missing fields")
    if value.get("schema_version") != 1:
        raise ToolResultAttestationError("PostTool attestation schema_version is unsupported")
    for field in ("task_id", "runtime_attestation_digest", "input_structural_digest", "result_structural_digest", "head_digest", "operation_digest", "attestation_digest"):
        item = value.get(field)
        if not isinstance(item, str) or not SHA256_RE.fullmatch(item):
            raise ToolResultAttestationError(f"PostTool {field} is invalid")
    task_epoch = value.get("task_epoch")
    epoch_id = value.get("epoch_id")
    if not isinstance(task_epoch, str) or not task_epoch or len(task_epoch) > 180:
        raise ToolResultAttestationError("PostTool task_epoch is invalid")
    if not isinstance(epoch_id, str) or not epoch_id or len(epoch_id) > 180:
        raise ToolResultAttestationError("PostTool epoch_id is invalid")
    expected_generation = value.get("expected_generation")
    if isinstance(expected_generation, bool) or not isinstance(expected_generation, int) or expected_generation < 0:
        raise ToolResultAttestationError("PostTool expected_generation is invalid")
    for field in ("tool_use_id", "parent_tool_use_id", "tool_name", "outcome", "result_stage", "tool_kind", "gate"):
        item = value.get(field)
        if not isinstance(item, str) or len(item) > 180:
            raise ToolResultAttestationError(f"PostTool {field} is invalid")
    if not value["tool_use_id"] or not value["tool_name"]:
        raise ToolResultAttestationError("PostTool tool identity is incomplete")
    if value["result_stage"] != "terminal":
        raise ToolResultAttestationError("PostTool result_stage must be terminal")
    if value["tool_kind"] not in {"implementation_write", "validation_gate"}:
        raise ToolResultAttestationError("PostTool tool_kind is not in the closed allowlist")
    if value["outcome"] not in {"success", "failure", "pass", "fail"}:
        raise ToolResultAttestationError("PostTool outcome is invalid")
    paths = value.get("relative_paths")
    if not isinstance(paths, list) or len(paths) > 64:
        raise ToolResultAttestationError("PostTool relative_paths is invalid")
    normalized_paths = []
    for path in paths:
        if not isinstance(path, str) or not path or len(path) > 240 or path.startswith("/") or ".." in path.split("/"):
            raise ToolResultAttestationError("PostTool relative_paths contains an unsafe path")
        normalized_paths.append(path)
    if tuple(sorted(set(normalized_paths))) != tuple(normalized_paths):
        raise ToolResultAttestationError("PostTool relative_paths must be sorted and unique")
    operation_id = value["operation_id"]
    if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 180:
        raise ToolResultAttestationError("PostTool operation_id is invalid")
    structural_material = {
        key: value[key] for key in sorted(_V1_FIELDS - {"operation_digest", "attestation_digest"})
    }
    if digest_value(structural_material) != value["attestation_digest"]:
        raise ToolResultAttestationError("PostTool attestation digest is not bound")
    if event_binding is not None:
        if set(event_binding) != _EVENT_BINDING_FIELDS:
            raise ToolResultAttestationError("PostTool runtime event binding is incomplete")
        if any(value.get(field) != event_binding.get(field) for field in _EVENT_BINDING_FIELDS):
            raise ToolResultAttestationError("PostTool attestation does not match the actual event")
    expected_transition = "POST_TOOL_RESULT_RECORDED"
    request = TransitionRequest(
        operation_id=operation_id,
        transition=expected_transition,
        expected_generation=expected_generation,
        evidence_ids=("post-tool:" + value["tool_use_id"],),
        actor_role="deterministic-runtime",
        evidence_manifest_digest=value["result_structural_digest"],
        reason=("tool-result:" + value["outcome"])[:512],
        task_id=value["task_id"],
        task_epoch=task_epoch,
        epoch_id=epoch_id,
        head_digest=value["head_digest"],
        runtime_attestation_digest=value["runtime_attestation_digest"],
        attestation_digest=value["attestation_digest"],
        tool_use_id=value["tool_use_id"],
        tool_kind=value["tool_kind"],
    )
    if request.operation_digest() != value["operation_digest"]:
        raise ToolResultAttestationError("PostTool operation digest is not bound")
    return request, value["attestation_digest"]


def structural_digest(value: object) -> str:
    """Hash a bounded type/length/value projection without retaining bodies."""

    return digest_value(_structural_projection(value, depth=0))


def _structural_projection(value: object, *, depth: int) -> object:
    if depth > 8:
        raise ToolResultAttestationError("PostTool event structure exceeds its depth limit")
    if value is None or isinstance(value, bool):
        return {"type": type(value).__name__, "value": value}
    if isinstance(value, int):
        return {"type": "int", "value": value}
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ToolResultAttestationError("PostTool event contains a non-finite number")
        return {"type": "float", "value": value}
    if isinstance(value, str):
        encoded = value.encode("utf-8", errors="replace")
        return {"type": "str", "bytes": len(encoded), "digest": digest_value(value)}
    if isinstance(value, Mapping):
        if len(value) > 128:
            raise ToolResultAttestationError("PostTool event object exceeds its item limit")
        rows = []
        for key in sorted(value, key=lambda item: str(item)):
            if not isinstance(key, str) or len(key) > 180:
                raise ToolResultAttestationError("PostTool event object has an invalid key")
            rows.append([digest_value(key), _structural_projection(value[key], depth=depth + 1)])
        return {"type": "object", "items": rows}
    if isinstance(value, (list, tuple)):
        if len(value) > 128:
            raise ToolResultAttestationError("PostTool event array exceeds its item limit")
        return {"type": "array", "items": [_structural_projection(item, depth=depth + 1) for item in value]}
    raise ToolResultAttestationError("PostTool event contains an unsupported value")


def _bounded_strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > 64:
        raise ToolResultAttestationError(f"PostTool {label} is invalid")
    result = tuple(str(item) for item in value)
    if any(not item or len(item) > 180 for item in result):
        raise ToolResultAttestationError(f"PostTool {label} contains an invalid value")
    return result


__all__ = ["ALLOWED_TRANSITIONS", "ToolResultAttestationError", "request_from_attestation", "structural_digest"]
