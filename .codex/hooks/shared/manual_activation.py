"""Content-addressed manual activation evidence for the enforce-only rollout.

The host in which this repository runs does not expose a trustworthy model
identity attestation.  The activation contract therefore makes that boundary
explicit: Codex main authorizes a bounded global-enforce activation, and the
approval artifact is bound to the exact plan, policy, workspace, branch and
HEAD.  It does *not* claim that the host proved a particular model identity.

The artifact is local operator state under ``.local-notes``.  It is read with
the same bounded, no-follow rules as the policy loader and is never populated
from hook payload fields.
"""
from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .convergent_contracts import SHA256_RE, digest_text, digest_value
from .execution_lease import LeaseEvidence
from .execution_policy import (
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


MANUAL_ACTIVATION_RELATIVE_PATH = ".local-notes/ralph/convergent-manual-activation.toml"
MANUAL_ACTIVATION_VERSION = 1
MAX_MANUAL_ACTIVATION_BYTES = 16 * 1024
MANUAL_ACTIVATION_SCOPE = "global-enforce"


class ManualActivationError(ExecutionPolicyError):
    """Raised when the explicit activation evidence is absent or stale."""


@dataclass(frozen=True)
class ManualActivation:
    tools: tuple[str, ...]
    workspace_fingerprint: str
    branch: str
    head_digest: str
    approval_digest: str

    @property
    def attestation_digest(self) -> str:
        """Compatibility name used by the existing transition contracts."""

        return self.approval_digest

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
            source="manual-approval",
        )


def manual_activation_payload(
    *,
    workspace_root: Path,
    branch: str,
    head_sha: str,
    tools: tuple[str, ...],
    policy: ExecutionPolicy,
    approval_id: str,
) -> dict[str, Any]:
    """Return canonical bytes for a user-approved local activation record."""

    _validate_tools(tools)
    branch = branch.strip()
    head_sha = head_sha.strip().lower()
    if not branch or len(branch) > 180:
        raise ManualActivationError("manual activation branch is invalid")
    if len(head_sha) not in {40, 64} or any(c not in "0123456789abcdef" for c in head_sha):
        raise ManualActivationError("manual activation HEAD must be a full digest")
    if not approval_id or len(approval_id) > 180:
        raise ManualActivationError("manual activation approval_id is invalid")
    material: dict[str, Any] = {
        "version": MANUAL_ACTIVATION_VERSION,
        "approval_id": approval_id,
        "approval_scope": MANUAL_ACTIVATION_SCOPE,
        "approved_by": AUTHORITY_ROLE,
        "plan_id": ACTIVATION_PLAN_ID,
        "plan_digest": ACTIVATION_PLAN_DIGEST,
        "policy_hash": policy.policy_hash,
        "workspace_fingerprint": digest_text(str(workspace_root.resolve())),
        "branch": branch,
        "head_digest": digest_text(head_sha),
        "tools": list(tools),
        "implementation_model_contract": REQUIRED_IMPLEMENTATION_MODEL,
        "reasoning_effort_contract": REQUIRED_REASONING_EFFORT,
    }
    return {**material, "approval_digest": digest_value(material)}


def load_manual_activation(
    workspace_root: Path,
    *,
    branch: str,
    head_sha: str,
    policy: ExecutionPolicy,
) -> ManualActivation:
    root = workspace_root.resolve()
    candidate = root / MANUAL_ACTIVATION_RELATIVE_PATH
    _validate_parent_chain(root, candidate)
    try:
        raw = _read_bounded_regular_file(
            candidate,
            hard_limit=MAX_MANUAL_ACTIVATION_BYTES,
            label="manual enforce activation",
        )
        # The repository intentionally carries a tiny TOML compatibility shim;
        # malformed input is normalized to one contract error regardless of
        # the TOML implementation available on the host.
        import tomllib

        decoded = tomllib.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ManualActivationError("manual enforce activation cannot be read") from exc
    if not isinstance(decoded, Mapping):
        raise ManualActivationError("manual enforce activation must be a table")
    expected_keys = {
        "version",
        "approval_id",
        "approval_scope",
        "approved_by",
        "plan_id",
        "plan_digest",
        "policy_hash",
        "workspace_fingerprint",
        "branch",
        "head_digest",
        "tools",
        "implementation_model_contract",
        "reasoning_effort_contract",
        "approval_digest",
    }
    if set(decoded) != expected_keys:
        raise ManualActivationError("manual enforce activation has unknown or missing fields")
    tools_value = decoded.get("tools")
    if not isinstance(tools_value, list):
        raise ManualActivationError("manual enforce activation tools must be an array")
    tools = tuple(str(value).strip() for value in tools_value)
    _validate_tools(tools)
    material = manual_activation_payload(
        workspace_root=root,
        branch=str(decoded.get("branch") or ""),
        head_sha=_head_from_digest(str(decoded.get("head_digest") or "")),
        tools=tools,
        policy=policy,
        approval_id=str(decoded.get("approval_id") or ""),
    )
    # Preserve the recorded head digest rather than requiring the irreversible
    # full SHA to be recoverable from the hash.  Rebuild the same canonical
    # material for exact digest verification below.
    material["head_digest"] = str(decoded.get("head_digest") or "")
    if decoded.get("approval_digest") != digest_value({k: material[k] for k in material if k != "approval_digest"}):
        raise ManualActivationError("manual enforce activation digest is invalid")
    if decoded.get("version") != MANUAL_ACTIVATION_VERSION:
        raise ManualActivationError("manual enforce activation version is unsupported")
    if decoded.get("approval_scope") != MANUAL_ACTIVATION_SCOPE:
        raise ManualActivationError("manual enforce activation scope is invalid")
    if decoded.get("approved_by") != AUTHORITY_ROLE:
        raise ManualActivationError("manual enforce activation requires Codex main approval")
    if decoded.get("plan_id") != ACTIVATION_PLAN_ID or decoded.get("plan_digest") != ACTIVATION_PLAN_DIGEST:
        raise ManualActivationError("manual enforce activation plan binding is stale")
    if decoded.get("policy_hash") != policy.policy_hash:
        raise ManualActivationError("manual enforce activation policy binding is stale")
    if decoded.get("implementation_model_contract") != REQUIRED_IMPLEMENTATION_MODEL:
        raise ManualActivationError("manual enforce activation model contract is invalid")
    if decoded.get("reasoning_effort_contract") != REQUIRED_REASONING_EFFORT:
        raise ManualActivationError("manual enforce activation effort contract is invalid")
    if decoded.get("workspace_fingerprint") != digest_text(str(root)):
        raise ManualActivationError("manual enforce activation workspace binding is stale")
    if decoded.get("branch") != branch:
        raise ManualActivationError("manual enforce activation branch binding is stale")
    expected_head_digest = digest_text(head_sha.strip().lower())
    if decoded.get("head_digest") != expected_head_digest:
        raise ManualActivationError("manual enforce activation HEAD binding is stale")
    return ManualActivation(
        tools=tools,
        workspace_fingerprint=str(decoded["workspace_fingerprint"]),
        branch=str(decoded["branch"]),
        head_digest=str(decoded["head_digest"]),
        approval_digest=str(decoded["approval_digest"]),
    )


def _validate_tools(tools: tuple[str, ...]) -> None:
    if not tools or len(tools) > 128:
        raise ManualActivationError("manual enforce activation toolset is invalid")
    if tuple(sorted(set(tools))) != tools or any(not item or len(item) > 160 for item in tools):
        raise ManualActivationError("manual enforce activation toolset must be sorted and bounded")


def _head_from_digest(value: str) -> str:
    # A digest is intentionally not reversible.  This sentinel is used only
    # while rebuilding the canonical record; the recorded digest is replaced
    # before comparison and the live HEAD check below remains authoritative.
    if not SHA256_RE.fullmatch(value):
        raise ManualActivationError("manual enforce activation HEAD digest is invalid")
    return "0" * 40


def _validate_parent_chain(root: Path, candidate: Path) -> None:
    try:
        candidate.relative_to(root)
        current = root
        for part in Path(MANUAL_ACTIVATION_RELATIVE_PATH).parts[:-1]:
            current = current / part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise ManualActivationError("manual enforce activation parent is unsafe")
        candidate.resolve().relative_to(root)
    except (OSError, ValueError) as exc:
        raise ManualActivationError("manual enforce activation path is unavailable") from exc


__all__ = [
    "MANUAL_ACTIVATION_RELATIVE_PATH",
    "ManualActivation",
    "ManualActivationError",
    "load_manual_activation",
    "manual_activation_payload",
]
