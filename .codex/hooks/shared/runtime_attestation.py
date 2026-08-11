"""Content-safe, local runtime attestation for enforce-mode v4 authority.

The checked-in activation descriptor names this fixed ignored path, but does
not create it. T15 must materialize the descriptor explicitly after Codex
main validates the real runtime. Hook payload metadata never substitutes for
this file.
"""
from __future__ import annotations

import stat
import hashlib
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .convergent_contracts import SHA256_RE, digest_text, digest_value
from .execution_lease import LeaseEvidence
from .execution_policy import (
    ACTIVATION_ATTESTATION_RELATIVE_PATH,
    ACTIVATION_PLAN_DIGEST,
    ACTIVATION_PLAN_ID,
    AUTHORITY_ROLE,
    IMPLEMENTATION_ROLE,
    REQUIRED_IMPLEMENTATION_MODEL,
    REQUIRED_REASONING_EFFORT,
    ExecutionPolicy,
    ExecutionPolicyError,
    _read_bounded_regular_file,
)


MAX_RUNTIME_ATTESTATION_BYTES = 16 * 1024
RUNTIME_ATTESTATION_VERSION = 1
ACTIVATION_APPROVAL_RELATIVE_PATH = ".ralph/plans/2026-08-11-ralph-convergent-execution-v4-amendment-001.md"
CONTRACT_SET_DIGEST = digest_value(
    {
        "authority": "v4-authority-2",
        "epoch": "v4-epoch-pointer-1",
        "post_tool": "v4-post-tool-evidence-1",
        "state_schema": 3,
        "policy_version": 4,
    }
)
_FIELDS = frozenset(
    {
        "version",
        "plan_id",
        "plan_digest",
        "policy_hash",
        "model",
        "reasoning_effort",
        "tools",
        "workspace_fingerprint",
        "branch_fingerprint",
        "head_digest",
        "authority_actor",
        "approval_artifact_digest",
        "contract_set_digest",
        "attestation_digest",
    }
)


class RuntimeAttestationError(ExecutionPolicyError):
    """The local runtime descriptor is absent, unsafe, stale, or unbound."""


@dataclass(frozen=True)
class RuntimeAttestation:
    tools: tuple[str, ...]
    head_digest: str
    approval_artifact_digest: str
    contract_set_digest: str
    attestation_digest: str

    def lease_evidence(self, *, cwd: str, branch: str, task_epoch: str) -> LeaseEvidence:
        return LeaseEvidence(
            model=REQUIRED_IMPLEMENTATION_MODEL,
            reasoning_effort=REQUIRED_REASONING_EFFORT,
            tools=self.tools,
            cwd=cwd,
            branch=branch,
            task_epoch=task_epoch,
            owner_role=IMPLEMENTATION_ROLE,
            authority_role=AUTHORITY_ROLE,
            source="verified-runtime",
        )


def runtime_attestation_payload(
    *,
    workspace_root: Path,
    branch: str,
    head_sha: str,
    tools: tuple[str, ...],
    policy: ExecutionPolicy,
    approval_artifact_digest: str,
) -> dict[str, Any]:
    """Build canonical descriptor data for the separately authorized T15 writer."""

    canonical_tools = _canonical_tools(tools)
    if not SHA256_RE.fullmatch(approval_artifact_digest):
        raise RuntimeAttestationError("runtime approval artifact digest is invalid")
    head_sha = head_sha.strip().lower()
    if len(head_sha) not in {40, 64} or any(character not in "0123456789abcdef" for character in head_sha):
        raise RuntimeAttestationError("runtime checkout HEAD must be a full 40/64-character digest")
    material: dict[str, Any] = {
        "version": RUNTIME_ATTESTATION_VERSION,
        "plan_id": ACTIVATION_PLAN_ID,
        "plan_digest": ACTIVATION_PLAN_DIGEST,
        "policy_hash": policy.policy_hash,
        "model": REQUIRED_IMPLEMENTATION_MODEL,
        "reasoning_effort": REQUIRED_REASONING_EFFORT,
        "tools": list(canonical_tools),
        "workspace_fingerprint": digest_text(str(workspace_root.resolve())),
        "branch_fingerprint": digest_text(branch),
        "head_digest": digest_text(head_sha.lower()),
        "authority_actor": AUTHORITY_ROLE,
        "approval_artifact_digest": approval_artifact_digest,
        "contract_set_digest": CONTRACT_SET_DIGEST,
    }
    return {**material, "attestation_digest": digest_value(material)}


def load_runtime_attestation(
    workspace_root: Path,
    *,
    branch: str,
    head_sha: str,
    policy: ExecutionPolicy,
) -> RuntimeAttestation:
    root = workspace_root.resolve()
    candidate = root / ACTIVATION_ATTESTATION_RELATIVE_PATH
    _validate_parent_chain(root, candidate)
    try:
        raw = _read_bounded_regular_file(
            candidate,
            hard_limit=MAX_RUNTIME_ATTESTATION_BYTES,
            label="convergent runtime attestation",
        )
        decoded = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, ExecutionPolicyError) as exc:
        raise RuntimeAttestationError("convergent runtime attestation cannot be validated") from exc
    if not isinstance(decoded, dict) or set(decoded) != _FIELDS:
        raise RuntimeAttestationError("convergent runtime attestation has unknown or missing keys")
    tools_value = decoded.get("tools")
    if not isinstance(tools_value, list):
        raise RuntimeAttestationError("convergent runtime attestation tools must be an array")
    tools = _canonical_tools(tuple(tools_value))
    expected = runtime_attestation_payload(
        workspace_root=root,
        branch=branch,
        head_sha=head_sha,
        tools=tools,
        policy=policy,
        approval_artifact_digest=str(decoded.get("approval_artifact_digest") or ""),
    )
    if decoded != expected:
        raise RuntimeAttestationError("convergent runtime attestation is stale or unbound")
    approval_path = root / ACTIVATION_APPROVAL_RELATIVE_PATH
    _validate_parent_chain_for(root, approval_path, ACTIVATION_APPROVAL_RELATIVE_PATH)
    try:
        approval_raw = _read_bounded_regular_file(
            approval_path,
            hard_limit=MAX_RUNTIME_ATTESTATION_BYTES,
            label="convergent activation approval",
        )
    except (ExecutionPolicyError, OSError) as exc:
        raise RuntimeAttestationError("convergent activation approval is unavailable") from exc
    approval_digest = "sha256:" + hashlib.sha256(approval_raw).hexdigest()
    if approval_digest != expected["approval_artifact_digest"]:
        raise RuntimeAttestationError("convergent activation approval digest is stale")
    return RuntimeAttestation(
        tools=tools,
        head_digest=expected["head_digest"],
        approval_artifact_digest=expected["approval_artifact_digest"],
        contract_set_digest=expected["contract_set_digest"],
        attestation_digest=expected["attestation_digest"],
    )


def _canonical_tools(values: tuple[object, ...]) -> tuple[str, ...]:
    if not values or len(values) > 128:
        raise RuntimeAttestationError("runtime toolset must be bounded and non-empty")
    tools = tuple(str(value).strip() for value in values)
    if any(not value or len(value) > 160 for value in tools):
        raise RuntimeAttestationError("runtime toolset contains an invalid name")
    if tuple(sorted(set(tools))) != tools:
        raise RuntimeAttestationError("runtime toolset must be sorted and duplicate-free")
    return tools


def _validate_parent_chain(root: Path, candidate: Path) -> None:
    _validate_parent_chain_for(root, candidate, ACTIVATION_ATTESTATION_RELATIVE_PATH)


def _validate_parent_chain_for(root: Path, candidate: Path, relative: str) -> None:
    try:
        candidate.relative_to(root)
        current = root
        for part in Path(relative).parts[:-1]:
            current = current / part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise RuntimeAttestationError("runtime attestation parent is unsafe")
        candidate.resolve().relative_to(root)
    except (OSError, ValueError) as exc:
        raise RuntimeAttestationError("runtime attestation path is unavailable") from exc


__all__ = [
    "RuntimeAttestation",
    "RuntimeAttestationError",
    "load_runtime_attestation",
    "runtime_attestation_payload",
]
