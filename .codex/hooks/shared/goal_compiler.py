"""Deterministic serial compiler for the approved v4 implementation goals."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping

from .convergent_contracts import IDENTIFIER_RE, SHA256_RE, digest_value
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
        "Implement Prompt Boundary classification in enforce mode without prompt-length task creation.",
        (".codex/hooks/shared/prompt_boundary.py", ".codex/hooks/user_prompt_dispatch.py", "tests/**"),
        ("All seven configured boundary classes are deterministic.", "Off rollback remains silent and enforce uses canonical authority."),
        ("boundary_matrix", "off_rollback_proof", "focused_tests"),
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
    active_plan: Mapping[str, Any] | None = None,
    decision_packet: Mapping[str, Any] | None = None,
    goal_id: str | None = None,
) -> tuple[GoalRecord, ...]:
    canonical_rollout = plan_id == PLAN_ID and plan_version == PLAN_VERSION
    if canonical_rollout and plan_digest != PLAN_DIGEST:
        _digest(plan_digest, "plan_digest")
        raise GoalCompileError("goal compiler plan_digest differs from the immutable approved plan")
    if not canonical_rollout and active_plan is None:
        raise GoalCompileError("goal compiler requires active plan metadata for a non-rollout logical plan")
    _digest(plan_digest, "plan_digest")
    if isinstance(state_generation, bool) or not isinstance(state_generation, int) or state_generation < 0:
        raise GoalCompileError("state_generation must be nonnegative")
    templates = TEMPLATES if canonical_rollout else _templates_from_active_plan(
        plan_id=plan_id,
        active_plan=active_plan or {},
        decision_packet=decision_packet,
        goal_id=goal_id,
    )
    goal_ids = tuple(template.goal_id for template in templates)
    if not goal_ids:
        raise GoalCompileError("active plan must compile at least one serial goal")
    completed_values = tuple(completed)
    completed_set = set(completed_values)
    if len(completed_values) != len(completed_set):
        raise GoalCompileError("completed goals contain duplicate goal IDs")
    if completed_set - set(goal_ids):
        raise GoalCompileError("completed goals contain an unknown goal ID")
    indexes = [goal_ids.index(item) for item in completed_set]
    if indexes and set(indexes) != set(range(max(indexes) + 1)):
        raise GoalCompileError("completed goals must form a serial prefix")

    owner = dict(OWNER_RECORD)
    records: list[GoalRecord] = []
    first_unfinished = len(completed_set)
    for index, template in enumerate(templates):
        status = "complete" if index < first_unfinished else "ready" if index == first_unfinished else "pending"
        prerequisites = () if index == 0 else (templates[index - 1].goal_id,)
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
        validate_goal(record, templates=templates if canonical_rollout else None)
        records.append(record)
    return tuple(records)


def validate_goal(goal: GoalRecord, *, templates: Iterable[_GoalTemplate] | None = None) -> None:
    if not isinstance(goal.goal_id, str) or not IDENTIFIER_RE.fullmatch(goal.goal_id) or goal.status not in GOAL_STATUSES or goal.risk not in {"low", "material", "critical"}:
        raise GoalCompileError("goal enum is invalid")
    if not goal.done_when or not goal.required_evidence or not goal.allowed_paths:
        raise GoalCompileError("goal omits required scope or completion evidence")
    if goal.plan_id == PLAN_ID and goal.plan_version == PLAN_VERSION and goal.plan_digest != PLAN_DIGEST:
        raise GoalCompileError("goal plan identity differs from the immutable approved plan")
    _digest(goal.plan_digest, "goal.plan_digest")
    if isinstance(goal.state_generation, bool) or not isinstance(goal.state_generation, int) or goal.state_generation < 0:
        raise GoalCompileError("goal state generation is invalid")
    if not SHA256_RE.fullmatch(goal.goal_digest):
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
    expected_templates = tuple(templates) if templates is not None else TEMPLATES if goal.plan_id == PLAN_ID and goal.plan_version == PLAN_VERSION and goal.plan_digest == PLAN_DIGEST else ()
    if expected_templates:
        template_by_id = {template.goal_id: template for template in expected_templates}
        template = template_by_id.get(goal.goal_id)
        if template is None:
            raise GoalCompileError("goal scope differs from its approved deterministic template")
        ordered_ids = tuple(item.goal_id for item in expected_templates)
        expected_prerequisites = () if goal.goal_id == ordered_ids[0] else (ordered_ids[ordered_ids.index(goal.goal_id) - 1],)
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


def _templates_from_active_plan(
    *,
    plan_id: str,
    active_plan: Mapping[str, Any],
    decision_packet: Mapping[str, Any] | None,
    goal_id: str | None,
) -> tuple[_GoalTemplate, ...]:
    """Compile a bounded serial goal set from the registered active plan.

    The v4 rollout templates remain immutable and are selected only by their
    exact plan identity.  Ordinary plans use their validated implementation
    store metadata, optionally enriched by a Decision Packet sequence.
    """

    packet = decision_packet if isinstance(decision_packet, Mapping) else {}
    sequence = packet.get("implementation_sequence")
    rows = sequence if isinstance(sequence, (list, tuple)) else ()
    if not rows:
        rows = active_plan.get("goals") if isinstance(active_plan.get("goals"), (list, tuple)) else ()
    fallback_id = goal_id or active_plan.get("goal_id") or f"G-{plan_id}"
    candidates: list[Mapping[str, Any]] = [row for row in rows if isinstance(row, Mapping)]
    if not candidates:
        candidates = [{"goal_id": fallback_id}]
    templates: list[_GoalTemplate] = []
    for index, row in enumerate(candidates):
        raw_id = row.get("goal_id") or (fallback_id if index == 0 else f"{fallback_id}-{index + 1}")
        if not isinstance(raw_id, str) or not IDENTIFIER_RE.fullmatch(raw_id):
            raise GoalCompileError("active plan goal_id is not a bounded identifier")
        raw_paths = _sequence_value(row.get("allowed_paths") or active_plan.get("active_files") or ())
        allowed = tuple(item for item in raw_paths if isinstance(item, str) and item.strip())
        if not allowed:
            plan_path = active_plan.get("plan_path")
            allowed = (str(plan_path),) if isinstance(plan_path, str) and plan_path else (".ralph/plans/**",)
        objective = row.get("objective") or packet.get("objective") or active_plan.get("objective") or f"Execute active plan {plan_id}."
        phase = row.get("phase_id") or active_plan.get("phase") or "active-plan"
        done = row.get("done_when") or packet.get("done_when") or ("The active plan objective has bounded verification evidence.",)
        done = _sequence_value(done)
        evidence = _sequence_value(row.get("required_evidence") or packet.get("verification_matrix") or ())
        if evidence:
            required = tuple(
                item if isinstance(item, str) else str(item.get("gate") or item.get("evidence_path") or "verification")
                for item in evidence
                if isinstance(item, (str, Mapping))
            )
        else:
            required = ("plan_state", "focused_verification")
        classification = str(active_plan.get("classification") or "GREEN").upper()
        risk = {"GREEN": "low", "YELLOW": "material", "RED": "critical"}.get(classification, "material")
        templates.append(
            _GoalTemplate(
                raw_id,
                str(phase)[:64],
                str(objective)[:480],
                _paths(allowed, "allowed_paths"),
                _nonempty(done, "done_when"),
                _nonempty(required, "required_evidence"),
                risk,
            )
        )
    if len({template.goal_id for template in templates}) != len(templates):
        raise GoalCompileError("active plan goals contain duplicate goal IDs")
    return tuple(templates)


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


def _sequence_value(value: object) -> tuple[object, ...]:
    """Normalize scalar plan metadata without iterating its characters."""
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return ()


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
