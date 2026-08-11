"""Strict, byte-hashed loader for the supplied Convergent Execution v4 policy.

The source TOML is a frozen public contract.  This module does not add fields
to it: runtime activation, storage bounds, lifecycle edges, and the exact SOL
lease are code-level contracts derived from the approved v4 design.
"""
from __future__ import annotations

import hashlib
import os
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Mapping

from .paths import REPO_ROOT


POLICY_VERSION: Final[int] = 4
EXPECTED_POLICY_SHA256: Final[str] = "aa7847050dad0821c83f456b31a42efa0d6eea8989b22b33ecc6edb2c26adbef"
DEFAULT_POLICY_PATH: Final[Path] = REPO_ROOT / "config" / "execution-policy.toml"
MAX_POLICY_BYTES: Final[int] = 64 * 1024
MAX_ACTIVATION_CONFIG_BYTES: Final[int] = 8 * 1024
REQUIRED_IMPLEMENTATION_MODEL: Final[str] = "gpt-5.6-sol"
REQUIRED_REASONING_EFFORT: Final[str] = "max"
AUTHORITY_ROLE: Final[str] = "codex-main"
IMPLEMENTATION_ROLE: Final[str] = "sol-worker"
ACTIVATION_CONFIG_PATH: Final[Path] = REPO_ROOT / "config" / "convergent-execution-mode.toml"
ACTIVATION_CONFIG_VERSION: Final[int] = 3
ACTIVATION_PLAN_ID: Final[str] = "ralph-convergent-execution-v4-20260811"
ACTIVATION_PLAN_DIGEST: Final[str] = "sha256:fead6e85227c68c863fa23ccccc30f559c3893ced514704f5643c61d1c41b5e1"
ACTIVATION_APPROVAL_RELATIVE_PATH: Final[str] = ".local-notes/ralph/convergent-manual-activation.toml"
# Compatibility import for the retired runtime-attestation module. Production
# authority loads the manual activation contract instead.
ACTIVATION_ATTESTATION_RELATIVE_PATH: Final[str] = ACTIVATION_APPROVAL_RELATIVE_PATH

BOUNDARY_CLASSES: Final[tuple[str, ...]] = (
    "status",
    "continuation",
    "clarification",
    "new-task",
    "scope-extension",
    "material-change",
    "user-override",
)
NORMAL_LIFECYCLE: Final[tuple[str, ...]] = (
    "NEW_TASK",
    "PROMPT_GATE",
    "ARISTOTLE",
    "DESIGN_READY",
    "IMPLEMENTATION",
    "FOCUSED_VERIFY",
    "REVIEW",
    "FINDING_TRIAGE",
    "MITIGATION",
    "FINAL_AUDIT",
    "ANTI_RATIONALIZATION",
    "STOP",
    "CLOSED",
)
TERMINAL_PHASES: Final[tuple[str, ...]] = ("CLOSED", "BLOCKED", "USER_DECISION")

_PRINCIPLE = (
    "Cada nueva evidencia debe acercar monotónicamente la tarea hacia CLOSED o hacia una decisión explícita "
    "del usuario. Ninguna fase puede reiniciar indefinidamente una fase anterior."
)

# Exact supplied v4 schema and values.  Lists remain lists here so TOML type
# validation is exact; the public dataclass exposes immutable tuples/maps.
POLICY_SPEC: Final[dict[str, Any]] = {
    "version": 4,
    "constitution": {
        "monotonic_convergence": True,
        "principle": _PRINCIPLE,
        "invalid_transition": "block",
        "budget_exhaustion": "user-decision",
    },
    "execution": {
        "mode": "convergent",
        "single_implementation_owner": True,
        "automatic_model_escalation": False,
        "freeze_decision_after_aristotle": True,
        "material_evidence_reopens_decision": True,
        "max_task_reopens": 1,
    },
    "prompt_boundary": {"enabled": True, "run_every_prompt": True, "classes": list(BOUNDARY_CLASSES)},
    "aristotle": {
        "enabled": True,
        "micro_max_complexity": 2,
        "quick_complexity": 3,
        "full_min_complexity": 4,
        "full_runs_per_task": 1,
        "material_amendments_per_task": 1,
        "third_reconsideration": "user-decision",
        "output": "decision-packet",
    },
    "model_selection": {
        "keep_model_stable": True,
        "keep_reasoning_effort_stable": True,
        "keep_toolset_stable": True,
        "keep_cwd_stable": True,
        "sol_advisor_automatic": False,
    },
    "delegation": {
        "automatic_subagents": 0,
        "max_active_children": 1,
        "hard_max_threads": 2,
        "max_depth": 1,
        "nested_delegation": False,
        "require_independent_block": True,
        "require_measurable_success": True,
        "require_non_overlapping_write_scope": True,
    },
    "guards": {
        "repo_boundary": "always",
        "git_safety": "always",
        "red_egress": "always",
        "worktree_integrity": "always",
        "stop_guard": "always",
    },
    "anti_rationalization": {
        "enabled": True,
        "run_on_prompt": False,
        "run_on_phase_exit": True,
        "run_on_stop": True,
        "phrase_detection": "signal-only",
        "objective_evidence": "authoritative",
        "ordinary_blocks_per_task": 1,
        "distinct_critical_block": 1,
        "duplicate_block": "physical-no-op",
        "budget_exhaustion": "user-decision",
        "spawn_model": False,
        "trigger_aristotle": False,
        "trigger_review": False,
    },
    "recall": {
        "enabled": True,
        "metadata_first": True,
        "selection_cache": True,
        "inject_mode": "delta",
        "body_reads_on_cache_hit": False,
        "rehydrate_on_context_epoch_change": True,
        "raw_inbox_default": False,
        "preserve_non_authoritative_boundary": True,
    },
    "repair": {
        "transient_identical_reruns": 1,
        "repairs_per_failure_fingerprint": 1,
        "maximum_total_repair_cycles": 3,
    },
    "review": {
        "automatic_passes_low_risk": 0,
        "automatic_passes_material": 1,
        "automatic_reaudit": False,
        "single_review_owner": True,
        "batch_repairs_by_root_cause": True,
    },
    "final_audit": {
        "mode": "deterministic",
        "automatic_generative_audit": 0,
        "critical_generative_audit_requires_approval": True,
    },
    "stop": {
        "ordinary_continuations": 1,
        "distinct_critical_continuations": 1,
        "duplicate_terminal_attempt": "physical-no-op",
        "budget_exhaustion": "user-decision",
    },
    "hooks": {
        "successful_read_fast_path": True,
        "aggregate_read_metrics_at_stop": True,
        "inject_only_changed_context": True,
        "pre_tool_guards_never_bypassed": True,
        "stop_hard_gates_never_bypassed": True,
        "effective_graph_doctor": True,
    },
    "progress": {
        "persist_full_state": True,
        "user_visible_mode": "delta",
        "normal_update_max_tokens": 150,
        "blocker_update_max_tokens": 250,
        "final_summary_max_tokens": 600,
    },
    "canary": {
        "required": True,
        "minimum_tasks": 20,
        "quality_gate": "no-open-p0-p1",
        "compare_same_task_corpus": True,
    },
}


class ExecutionPolicyError(ValueError):
    """Raised when the policy is unsafe, malformed, or differs from v4."""


class PolicyDriftError(ExecutionPolicyError):
    """Raised when the active epoch and current policy hashes differ."""


@dataclass(frozen=True)
class ExecutionPolicy:
    version: int
    policy_hash: str
    source_path: str
    sections: Mapping[str, Mapping[str, Any]]

    def section(self, name: str) -> Mapping[str, Any]:
        try:
            return self.sections[name]
        except KeyError as exc:
            raise ExecutionPolicyError(f"unknown normalized policy section: {name}") from exc

    def as_dict(self) -> dict[str, Any]:
        return {"version": self.version, **{name: dict(values) for name, values in self.sections.items()}, "policy_hash": self.policy_hash}

    @property
    def full_aristotle_budget(self) -> int:
        return int(self.section("aristotle")["full_runs_per_task"])

    @property
    def amendment_budget(self) -> int:
        return int(self.section("aristotle")["material_amendments_per_task"])

    @property
    def automatic_children(self) -> int:
        return int(self.section("delegation")["automatic_subagents"])

    @property
    def active_child_max(self) -> int:
        return int(self.section("delegation")["max_active_children"])

    @property
    def review_budget_material(self) -> int:
        return int(self.section("review")["automatic_passes_material"])

    @property
    def transient_rerun_budget(self) -> int:
        return int(self.section("repair")["transient_identical_reruns"])

    @property
    def repair_per_fingerprint(self) -> int:
        return int(self.section("repair")["repairs_per_failure_fingerprint"])

    @property
    def total_repair_budget(self) -> int:
        return int(self.section("repair")["maximum_total_repair_cycles"])

    @property
    def ordinary_stop_budget(self) -> int:
        return int(self.section("stop")["ordinary_continuations"])

    @property
    def critical_stop_budget(self) -> int:
        return int(self.section("stop")["distinct_critical_continuations"])


def load_execution_policy(path: Path | str | None = None) -> ExecutionPolicy:
    candidate = Path(path) if path is not None else DEFAULT_POLICY_PATH
    raw = _read_policy(candidate)
    try:
        decoded = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ExecutionPolicyError("execution policy is not valid UTF-8 TOML") from exc
    _validate_exact(decoded, POLICY_SPEC, "policy")
    byte_hash = hashlib.sha256(raw).hexdigest()
    if byte_hash != EXPECTED_POLICY_SHA256:
        raise ExecutionPolicyError("execution policy bytes differ from the supplied v4 contract")
    sections = {
        name: MappingProxyType(_freeze_values(values))
        for name, values in decoded.items()
        if name != "version" and isinstance(values, Mapping)
    }
    return ExecutionPolicy(
        version=POLICY_VERSION,
        policy_hash="sha256:" + byte_hash,
        source_path=str(candidate.absolute()),
        sections=MappingProxyType(sections),
    )


def assert_policy_compatible(active_policy_hash: object, policy: ExecutionPolicy) -> None:
    active = str(active_policy_hash or "").strip()
    if active and active != policy.policy_hash:
        raise PolicyDriftError("execution policy changed during an active task epoch")


def configured_activation_mode(
    env: Mapping[str, str] | None = None,
    *,
    workspace_root: Path | str | None = None,
) -> str:
    """Resolve the versioned repo-local rollout mode.

    A supplied mapping is an intentionally isolated test/rollback override.
    Production calls read the repo-local, plan-bound activation file; a missing
    file is ``off`` so a globally installed hook cannot activate v4 in an
    unrelated project.  ``enforce`` is the only active convergence mode.  The
    only demotion is the explicit ``off`` rollback path; the former ``shadow``
    mode is rejected rather than silently reinterpreted.
    """

    if env is not None:
        value = str(env.get("RALPH_CONVERGENT_EXECUTION_MODE", "off")).strip().lower()
        return _validate_activation_mode(value, "RALPH_CONVERGENT_EXECUTION_MODE")

    workspace = Path(workspace_root or os.environ.get("RALPH_CONVERGENT_WORKSPACE_ROOT", str(REPO_ROOT))).expanduser().resolve()
    expected_path = (workspace / "config" / "convergent-execution-mode.toml").resolve()
    override = os.environ.get("RALPH_CONVERGENT_EXECUTION_CONFIG")
    config_path = Path(override).expanduser().resolve() if override else expected_path
    if config_path != expected_path:
        raise ExecutionPolicyError("RALPH_CONVERGENT_EXECUTION_CONFIG must be the active workspace activation file")
    if not config_path.exists():
        configured = "off"
    else:
        configured = _read_activation_config(config_path)
    environment_value = os.environ.get("RALPH_CONVERGENT_EXECUTION_MODE")
    if environment_value is None:
        return configured
    requested = _validate_activation_mode(environment_value.strip().lower(), "RALPH_CONVERGENT_EXECUTION_MODE")
    if configured == "off" and requested != "off":
        raise ExecutionPolicyError("RALPH_CONVERGENT_EXECUTION_MODE cannot promote an off rollout")
    if requested == "shadow":
        raise ExecutionPolicyError("RALPH_CONVERGENT_EXECUTION_MODE shadow mode is retired")
    return requested


def _validate_activation_mode(value: str, source: str) -> str:
    if value not in {"off", "enforce"}:
        raise ExecutionPolicyError(f"{source} must be off or enforce; shadow mode is retired")
    return value


def _read_activation_config(path: Path) -> str:
    raw = _read_bounded_regular_file(
        path,
        hard_limit=MAX_ACTIVATION_CONFIG_BYTES,
        label="convergent activation config",
    )
    try:
        decoded = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ExecutionPolicyError("convergent activation config is not valid UTF-8 TOML") from exc
    expected_keys = {"version", "mode", "plan_id", "plan_digest", "policy_hash", "activation_approval"}
    if not isinstance(decoded, dict) or set(decoded) != expected_keys:
        raise ExecutionPolicyError("convergent activation config has unknown or missing keys")
    if decoded.get("version") != ACTIVATION_CONFIG_VERSION:
        raise ExecutionPolicyError("convergent activation config version is unsupported")
    mode = decoded.get("mode")
    if not isinstance(mode, str):
        raise ExecutionPolicyError("convergent activation mode must be a string")
    _validate_activation_mode(mode.strip().lower(), "convergent activation mode")
    if decoded.get("plan_id") != ACTIVATION_PLAN_ID:
        raise ExecutionPolicyError("convergent activation config plan_id does not match the approved plan")
    if decoded.get("plan_digest") != ACTIVATION_PLAN_DIGEST:
        raise ExecutionPolicyError("convergent activation config plan_digest does not match the approved plan")
    if decoded.get("activation_approval") != ACTIVATION_APPROVAL_RELATIVE_PATH:
        raise ExecutionPolicyError("convergent activation config activation_approval path is unsupported")
    policy_hash = "sha256:" + EXPECTED_POLICY_SHA256
    if decoded.get("policy_hash") != policy_hash:
        raise ExecutionPolicyError("convergent activation config policy_hash does not match execution policy")
    return mode.strip().lower()


def _read_policy(path: Path) -> bytes:
    return _read_bounded_regular_file(path, hard_limit=MAX_POLICY_BYTES, label="execution policy")


def _read_bounded_regular_file(path: Path, *, hard_limit: int, label: str) -> bytes:
    """Read one stable, regular, single-link descriptor through ``O_NOFOLLOW``."""

    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ExecutionPolicyError(f"{label} must be a regular non-aliased file")
        if before.st_size > hard_limit:
            raise ExecutionPolicyError(f"{label} exceeds its byte limit")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ExecutionPolicyError(f"{label} could not be opened safely") from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or opened.st_size > hard_limit:
            raise ExecutionPolicyError(f"{label} changed to an unsafe file")
        if (opened.st_dev, opened.st_ino, opened.st_size) != (before.st_dev, before.st_ino, before.st_size):
            raise ExecutionPolicyError(f"{label} changed before it could be opened")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(16 * 1024, hard_limit - total + 1))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > hard_limit:
                raise ExecutionPolicyError(f"{label} exceeds its byte limit")
        final = os.fstat(fd)
        if (final.st_dev, final.st_ino, final.st_size) != (opened.st_dev, opened.st_ino, total):
            raise ExecutionPolicyError(f"{label} changed during read")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _validate_exact(actual: object, expected: object, label: str) -> None:
    if isinstance(expected, dict):
        if not isinstance(actual, Mapping):
            raise ExecutionPolicyError(f"{label} must be a table")
        unknown = sorted(set(actual) - set(expected))
        missing = sorted(set(expected) - set(actual))
        if unknown:
            raise ExecutionPolicyError(f"{label} has unknown keys: {', '.join(unknown)}")
        if missing:
            raise ExecutionPolicyError(f"{label} is missing keys: {', '.join(missing)}")
        for key, expected_value in expected.items():
            _validate_exact(actual[key], expected_value, f"{label}.{key}")
        return
    if isinstance(expected, list):
        if not isinstance(actual, list):
            raise ExecutionPolicyError(f"{label} must be an array")
        if len(actual) != len(expected):
            raise ExecutionPolicyError(f"{label} must preserve the canonical array")
        for index, (actual_value, expected_value) in enumerate(zip(actual, expected, strict=True)):
            _validate_exact(actual_value, expected_value, f"{label}[{index}]")
        return
    if type(actual) is not type(expected) or actual != expected:
        raise ExecutionPolicyError(f"{label} must equal the supplied v4 value")


def _freeze_values(values: Mapping[str, Any]) -> dict[str, Any]:
    frozen: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, list):
            frozen[key] = tuple(value)
        elif isinstance(value, Mapping):
            frozen[key] = MappingProxyType(_freeze_values(value))
        else:
            frozen[key] = value
    return frozen


__all__ = [
    "AUTHORITY_ROLE",
    "ACTIVATION_APPROVAL_RELATIVE_PATH",
    "BOUNDARY_CLASSES",
    "DEFAULT_POLICY_PATH",
    "EXPECTED_POLICY_SHA256",
    "ExecutionPolicy",
    "ExecutionPolicyError",
    "IMPLEMENTATION_ROLE",
    "NORMAL_LIFECYCLE",
    "POLICY_SPEC",
    "POLICY_VERSION",
    "PolicyDriftError",
    "REQUIRED_IMPLEMENTATION_MODEL",
    "REQUIRED_REASONING_EFFORT",
    "TERMINAL_PHASES",
    "assert_policy_compatible",
    "configured_activation_mode",
    "load_execution_policy",
]
