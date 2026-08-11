"""Deterministic serial compiler for the approved v4 implementation goals."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping

from .convergent_contracts import SHA256_RE, digest_value
from .execution_policy import AUTHORITY_ROLE, IMPLEMENTATION_ROLE, REQUIRED_IMPLEMENTATION_MODEL, REQUIRED_REASONING_EFFORT


PLAN_ID: Final[str] = "ralph-convergent-execution-v4-20260811"
PLAN_VERSION: Final[int] = 1
PLAN_DIGEST: Final[str] = "sha256:fead6e85227c68c863fa23ccccc30f559c3893ced514704f5643c61d1c41b5e1"
GOAL_IDS: Final[tuple[str, ...]] = (
    "G-BASELINE",
    "G-BOUNDARY",
    "G-DECISION",
    "G-LEASE",
    "G-RECALL-HOTPATH",
    "G-EVIDENCE-CLOSE",
    "G-DOCUMENTATION",
    "G-SHADOW-CANARY",
    "G-ROLLOUT",
)
GOAL_STATUSES: Final[frozenset[str]] = frozenset(
    {"pending", "ready", "active", "verifying", "complete", "blocked", "user-decision"}
)
DEFAULT_FORBIDDEN: Final[tuple[str, ...]] = (
    ".git/**",
    ".env",
    ".env.*",
    "**/*secret*",
    "**/*credential*",
    "ralph-convergent-execution-site/index.html",
)
OWNER_RECORD: Final[Mapping[str, Any]] = MappingProxyType(
    {
        "authority": AUTHORITY_ROLE,
        "implementation": IMPLEMENTATION_ROLE,
        "authority_role": AUTHORITY_ROLE,
        "implementation_owner": IMPLEMENTATION_ROLE,
        "model": REQUIRED_IMPLEMENTATION_MODEL,
        "reasoning_effort": REQUIRED_REASONING_EFFORT,
        "automatic_fallback": False,
    }
)


class GoalCompileError(ValueError):
    """Raised when plan identity, serial order, or scope is invalid."""


@dataclass(frozen=True)
class GoalRecord:
    goal_id: str
    plan_id: str
    plan_version: int
    plan_digest: str
    phase_id: str
    state_generation: int
    objective: str
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    prerequisites: tuple[str, ...]
    done_when: tuple[str, ...]
    required_evidence: tuple[str, ...]
    risk: str
    owner: Mapping[str, Any]
    status: str
    goal_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "plan_id": self.plan_id,
            "plan_version": self.plan_version,
            "plan_digest": self.plan_digest,
            "phase_id": self.phase_id,
            "state_generation": self.state_generation,
            "objective": self.objective,
            "allowed_paths": list(self.allowed_paths),
            "forbidden_paths": list(self.forbidden_paths),
            "prerequisites": list(self.prerequisites),
            "done_when": list(self.done_when),
            "required_evidence": list(self.required_evidence),
            "risk": self.risk,
            "owner": dict(self.owner),
            "status": self.status,
            "goal_digest": self.goal_digest,
        }


@dataclass(frozen=True)
class _GoalTemplate:
    goal_id: str
    phase_id: str
    objective: str
    allowed_paths: tuple[str, ...]
    done_when: tuple[str, ...]
    required_evidence: tuple[str, ...]
    risk: str


TEMPLATES: Final[tuple[_GoalTemplate, ...]] = (
    _GoalTemplate(
        "G-BASELINE",
        "T0-T1",
        "Reconcile source artifacts, preserve the exact policy, and prove one effective blocking owner per hook domain.",
        ("config/execution-policy.toml", ".codex/hooks/shared/execution_policy.py", ".codex/hooks/shared/effective_hook_graph.py", "scripts/setup/**", "tests/**"),
        ("Exact policy hash is verified.", "Effective hook graph fails duplicate blocking owners and warns report-only duplicates."),
        ("policy_hash", "hook_graph_report", "focused_tests"),
        "material",
    ),
    _GoalTemplate(
        "G-BOUNDARY",
        "T2",
        "Implement Prompt Boundary classification in shadow mode without prompt-length task creation.",
        (".codex/hooks/shared/prompt_boundary.py", ".codex/hooks/user_prompt_dispatch.py", "tests/**"),
        ("All seven configured boundary classes are deterministic.", "Default hook output remains unchanged in shadow mode."),
        ("boundary_matrix", "shadow_noop_proof", "focused_tests"),
        "material",
    ),
    _GoalTemplate(
        "G-DECISION",
        "T3-T4",
        "Compile serial goals and enforce Decision Packet, amendment, reducer, replay, and CAS contracts.",
        (".codex/hooks/shared/convergent_*.py", ".codex/hooks/shared/decision_packet.py", ".codex/hooks/shared/goal_compiler.py", ".codex/hooks/shared/implementation_store/**", "tests/**"),
        ("Goal and packet compilation are deterministic.", "Stale, duplicate-conflicting, out-of-order, corrupt-tail, future-schema, and tampered mutations block."),
        ("goal_digest", "packet_fingerprint", "replay_matrix", "focused_tests"),
        "critical",
    ),
    _GoalTemplate(
        "G-LEASE",
        "T5",
        "Require a stable real gpt-5.6-sol/max execution lease with no automatic fallback or delegation.",
        (".codex/hooks/shared/execution_lease.py", ".codex/hooks/shared/agent_budget.py", ".codex/hooks/shared/subagent_routing.py", ".codex/hooks/shared/sol_advisor.py", "tests/**"),
        ("Luna, Terra, advisor, non-max, drifted toolset/CWD/branch/epoch, and fallback evidence are rejected.", "Automatic child count remains zero."),
        ("lease_matrix", "delegation_zero_proof", "focused_tests"),
        "critical",
    ),
    _GoalTemplate(
        "G-RECALL-HOTPATH",
        "T6-T7",
        "Implement metadata-first Recall deltas and materiality-first hook fast paths without bypassing PreTool safety.",
        (".codex/hooks/shared/recall_delta.py", ".codex/hooks/shared/convergent_hooks.py", ".codex/hooks/user_prompt_dispatch.py", ".codex/hooks/pre_tool_dispatch.py", ".codex/hooks/post_tool_dispatch.py", "scripts/memory/**", "tests/**"),
        ("Same selection and context epoch perform zero body reads and zero context.", "Successful non-material reads perform zero durable writes while PreTool guards remain active."),
        ("recall_delta_matrix", "read_noop_metrics", "guardrail_tests"),
        "critical",
    ),
    _GoalTemplate(
        "G-EVIDENCE-CLOSE",
        "T8-T11",
        "Consolidate evidence-authoritative anti-rationalization, finite Stop, review triage, batch mitigation, and deterministic final audit.",
        (".codex/hooks/shared/convergent_review.py", ".codex/hooks/shared/final_audit.py", ".codex/hooks/shared/convergent_hooks.py", ".codex/hooks/stop_dispatch.py", ".codex/hooks/anti-rationalization-stop.sh", "skills/autoreview/**", "tests/**"),
        ("Low risk performs zero review and material/critical at most one.", "Accepted findings close in one root-cause batch.", "Close requires deterministic all-pass evidence and duplicate terminal attempts are physical no-ops."),
        ("review_ledger", "final_audit_digest", "stop_budget_matrix", "focused_tests"),
        "critical",
    ),
    _GoalTemplate(
        "G-DOCUMENTATION",
        "T10",
        "Update repository documentation and editable diagrams to the verified v4 runtime contract.",
        ("README.md", "docs/**", "AGENTS.md", "CLAUDE.md"),
        ("Documentation matches current code and preserves editable JSON/SVG/PNG diagram sources.",),
        ("doc_diff", "diagram_validation"),
        "material",
    ),
    _GoalTemplate(
        "G-SHADOW-CANARY",
        "T12-T13",
        "Compare current and candidate behavior over the same 24-scenario corpus and enforce canary hard gates.",
        ("scripts/evals/**", "tests/**", "docs/reports/**", "config/scorecards/**"),
        ("All 24 paired scenarios pass with zero safety, budget, or quality regressions.", "At least one declared structural metric improves by 20 percent without more than 10 percent regression."),
        ("paired_canary_report", "quality_gate", "rollback_test"),
        "critical",
    ),
    _GoalTemplate(
        "G-ROLLOUT",
        "T14-T15",
        "Enable the repository flag and prepare separately approved global backup/parity/doctor/smoke/rollback rollout.",
        (".codex/**", "scripts/setup/**", "docs/**", "tests/**"),
        ("Repository rollout passes before any global mutation.", "Global rollout remains approval-bound and rollback-tested."),
        ("repo_flag_gate", "global_approval", "backup_manifest", "doctor_smoke", "rollback_proof"),
        "critical",
    ),
)


def compile_goals(
    *,
    plan_id: str,
    plan_version: int,
    plan_digest: str,
    state_generation: int,
    completed: Iterable[str] = (),
) -> tuple[GoalRecord, ...]:
    if plan_id != PLAN_ID or plan_version != PLAN_VERSION:
        raise GoalCompileError("goal compiler is bound to the approved logical plan ID/version")
    _digest(plan_digest, "plan_digest")
    if plan_digest != PLAN_DIGEST:
        raise GoalCompileError("goal compiler plan_digest differs from the immutable approved plan")
    if isinstance(state_generation, bool) or not isinstance(state_generation, int) or state_generation < 0:
        raise GoalCompileError("state_generation must be nonnegative")
    completed_values = tuple(completed)
    completed_set = set(completed_values)
    if len(completed_values) != len(completed_set):
        raise GoalCompileError("completed goals contain duplicate goal IDs")
    if completed_set - set(GOAL_IDS):
        raise GoalCompileError("completed goals contain an unknown goal ID")
    indexes = [GOAL_IDS.index(item) for item in completed_set]
    if indexes and set(indexes) != set(range(max(indexes) + 1)):
        raise GoalCompileError("completed goals must form a serial prefix")

    owner = dict(OWNER_RECORD)
    records: list[GoalRecord] = []
    first_unfinished = len(completed_set)
    for index, template in enumerate(TEMPLATES):
        status = "complete" if index < first_unfinished else "ready" if index == first_unfinished else "pending"
        prerequisites = () if index == 0 else (TEMPLATES[index - 1].goal_id,)
        material = {
            "goal_id": template.goal_id,
            "plan_id": plan_id,
            "plan_version": plan_version,
            "plan_digest": plan_digest,
            "phase_id": template.phase_id,
            "state_generation": state_generation,
            "objective": template.objective,
            "allowed_paths": list(template.allowed_paths),
            "forbidden_paths": list(DEFAULT_FORBIDDEN),
            "prerequisites": list(prerequisites),
            "done_when": list(template.done_when),
            "required_evidence": list(template.required_evidence),
            "risk": template.risk,
            "owner": owner,
            "status": status,
        }
        record = GoalRecord(
            goal_id=template.goal_id,
            plan_id=plan_id,
            plan_version=plan_version,
            plan_digest=plan_digest,
            phase_id=template.phase_id,
            state_generation=state_generation,
            objective=template.objective,
            allowed_paths=_paths(template.allowed_paths, "allowed_paths"),
            forbidden_paths=_paths(DEFAULT_FORBIDDEN, "forbidden_paths"),
            prerequisites=prerequisites,
            done_when=_nonempty(template.done_when, "done_when"),
            required_evidence=_nonempty(template.required_evidence, "required_evidence"),
            risk=template.risk,
            owner=MappingProxyType(dict(owner)),
            status=status,
            goal_digest=digest_value(material),
        )
        validate_goal(record)
        records.append(record)
    return tuple(records)


def validate_goal(goal: GoalRecord) -> None:
    if goal.goal_id not in GOAL_IDS or goal.status not in GOAL_STATUSES or goal.risk not in {"low", "material", "critical"}:
        raise GoalCompileError("goal enum is invalid")
    if not goal.done_when or not goal.required_evidence or not goal.allowed_paths:
        raise GoalCompileError("goal omits required scope or completion evidence")
    if goal.plan_id != PLAN_ID or goal.plan_version != PLAN_VERSION or goal.plan_digest != PLAN_DIGEST:
        raise GoalCompileError("goal plan identity differs from the immutable approved plan")
    if isinstance(goal.state_generation, bool) or not isinstance(goal.state_generation, int) or goal.state_generation < 0:
        raise GoalCompileError("goal state generation is invalid")
    if not goal.goal_digest.startswith("sha256:") or len(goal.goal_digest) != 71:
        raise GoalCompileError("goal digest is invalid")
    required_owner = {
        "authority": AUTHORITY_ROLE,
        "implementation": IMPLEMENTATION_ROLE,
        "model": REQUIRED_IMPLEMENTATION_MODEL,
        "reasoning_effort": REQUIRED_REASONING_EFFORT,
    }
    if any(goal.owner.get(key) != expected for key, expected in required_owner.items()):
        raise GoalCompileError("goal owner does not match the approved Codex/SOL contract")
    if dict(goal.owner) != dict(OWNER_RECORD):
        raise GoalCompileError("goal owner contains unknown or missing fields")
    _paths(goal.allowed_paths, "allowed_paths")
    _paths(goal.forbidden_paths, "forbidden_paths")
    template = TEMPLATES[GOAL_IDS.index(goal.goal_id)]
    expected_prerequisites = () if goal.goal_id == GOAL_IDS[0] else (GOAL_IDS[GOAL_IDS.index(goal.goal_id) - 1],)
    if (
        goal.phase_id != template.phase_id
        or goal.objective != template.objective
        or goal.allowed_paths != template.allowed_paths
        or goal.forbidden_paths != DEFAULT_FORBIDDEN
        or goal.prerequisites != expected_prerequisites
        or goal.done_when != template.done_when
        or goal.required_evidence != template.required_evidence
        or goal.risk != template.risk
    ):
        raise GoalCompileError("goal scope differs from its approved deterministic template")
    material = goal.as_dict()
    material.pop("goal_digest")
    if goal.goal_digest != digest_value(material):
        raise GoalCompileError("goal digest does not match its record")


def _paths(values: Iterable[str], label: str) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value or value.startswith(("/", "~")) or ".." in PurePosixPath(value).parts:
            raise GoalCompileError(f"{label} contains an unsafe path")
        result.append(value)
    if not result or len(set(result)) != len(result):
        raise GoalCompileError(f"{label} must be non-empty and unique")
    return tuple(result)


def _nonempty(values: Iterable[str], label: str) -> tuple[str, ...]:
    result = tuple(value.strip() for value in values if isinstance(value, str) and value.strip())
    if not result or len(set(result)) != len(result):
        raise GoalCompileError(f"{label} must be non-empty and unique")
    return result


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise GoalCompileError(f"{label} must be a sha256 digest")
    return value


__all__ = [
    "GOAL_IDS",
    "PLAN_DIGEST",
    "PLAN_ID",
    "PLAN_VERSION",
    "OWNER_RECORD",
    "GoalCompileError",
    "GoalRecord",
    "compile_goals",
    "validate_goal",
]
