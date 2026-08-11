from __future__ import annotations

import json
import os
import hashlib
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

import shared.convergent_store as store_module  # noqa: E402
from shared.convergent_contracts import (  # noqa: E402
    FutureExecutionSchemaError,
    TaskIdentity,
    digest_value,
    event_hash,
    new_state,
    state_hash,
    validate_event,
)
from shared.convergent_reducer import TransitionError, TransitionRequest  # noqa: E402
from shared.convergent_store import (  # noqa: E402
    ConvergentIdempotencyError,
    ConvergentIntegrityError,
    ConvergentStore,
)
from shared.decision_packet import AmendmentApproval, DecisionAmendment  # noqa: E402
from shared.execution_lease import LeaseEvidence, acquire_execution_lease  # noqa: E402
from shared.execution_policy import PolicyDriftError, load_execution_policy  # noqa: E402
from shared.goal_compiler import GOAL_IDS, PLAN_ID  # noqa: E402
from shared.implementation_store import ImplementationStore, resolve_store_paths  # noqa: E402


PLAN_DIGEST = "sha256:fead6e85227c68c863fa23ccccc30f559c3893ced514704f5643c61d1c41b5e1"
PLAN_FIXTURE = ROOT / "tests" / "fixtures" / "ralph-convergent-execution-v4-plan.md"


def git(cwd: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "Test User")
    git(root, "config", "user.email", "test@example.invalid")
    (root / "README.md").write_text("# fixture\n", encoding="utf-8")
    git(root, "add", "README.md")
    git(root, "commit", "-m", "initial")
    return root


def make_store(tmp_path: Path) -> tuple[Path, ConvergentStore]:
    root = make_repo(tmp_path)
    (root / ".ralph" / "plans").mkdir(parents=True)
    # The canonical local plan is intentionally ignored and is not present in
    # a fresh PR checkout.  Tests use the byte-identical, versioned fixture so
    # plan provenance remains reproducible without depending on local ledgers.
    shutil.copyfile(PLAN_FIXTURE, root / ".ralph" / "plans" / "v4.md")
    progress = ImplementationStore(resolve_store_paths(primary_root=root))
    progress.register_plan(PLAN_ID, plan_path=".ralph/plans/v4.md", operation_id="op-register-v4")
    return root, ConvergentStore(progress, load_execution_policy())


def initial_state() -> dict:
    identity = TaskIdentity.from_values(
        session="session-store",
        project="project-store",
        worktree="workspace-store",
        branch="codex/ralph-convergent-execution-v4",
        objective="Implement v4 store",
        boundary_epoch=1,
        sensitivity="GREEN",
        plan=PLAN_ID,
        plan_version=1,
        plan_digest=PLAN_DIGEST,
    )
    return new_state(
        policy=load_execution_policy(),
        plan_id=PLAN_ID,
        plan_version=1,
        plan_digest=PLAN_DIGEST,
        task_identity=identity,
        goal_id="G-DECISION",
        task_epoch="epoch-store",
        boundary_epoch=1,
        boundary_kind="new_task",
        activation_mode="shadow",
    )


def boundary_request(state: dict, operation_id: str = "op-boundary") -> TransitionRequest:
    evidence = LeaseEvidence(
        model="gpt-5.6-sol",
        reasoning_effort="max",
        tools=("apply_patch", "exec_command"),
        cwd=str(ROOT),
        branch="codex/ralph-convergent-execution-v4",
        task_epoch="epoch-store",
        owner_role="sol-worker",
        authority_role="codex-main",
        source="verified-runtime",
    )
    lease = acquire_execution_lease(evidence, policy=load_execution_policy(), issued_generation=state["generation"])
    return TransitionRequest(
        operation_id=operation_id,
        transition="BOUNDARY_CLASSIFIED",
        expected_generation=state["generation"],
        lease=lease,
    )


def epoch_candidate(epoch: str, objective: str, boundary_epoch: int, operation_id: str) -> tuple[dict, TransitionRequest]:
    identity = TaskIdentity.from_values(
        session=f"session-{epoch}",
        project="project-store",
        worktree="workspace-store",
        branch="codex/ralph-convergent-execution-v4",
        objective=objective,
        boundary_epoch=boundary_epoch,
        sensitivity="GREEN",
        plan=PLAN_ID,
        plan_version=1,
        plan_digest=PLAN_DIGEST,
    )
    candidate = new_state(
        policy=load_execution_policy(),
        plan_id=PLAN_ID,
        plan_version=1,
        plan_digest=PLAN_DIGEST,
        task_identity=identity,
        goal_id="G-BASELINE",
        task_epoch=epoch,
        boundary_epoch=boundary_epoch,
        boundary_kind="new_task",
        activation_mode="shadow",
    )
    evidence = LeaseEvidence(
        model="gpt-5.6-sol",
        reasoning_effort="max",
        tools=("apply_patch", "exec_command"),
        cwd=str(ROOT),
        branch="codex/ralph-convergent-execution-v4",
        task_epoch=epoch,
        owner_role="sol-worker",
        authority_role="codex-main",
        source="verified-runtime",
    )
    lease = acquire_execution_lease(evidence, policy=load_execution_policy(), issued_generation=0)
    request = TransitionRequest(
        operation_id=operation_id,
        transition="BOUNDARY_CLASSIFIED",
        expected_generation=0,
        evidence_ids=("epoch-rotation",),
        actor_role="deterministic-runtime",
        lease=lease,
    )
    return candidate, request


def test_start_transition_idempotency_and_conflict(tmp_path: Path) -> None:
    _root, store = make_store(tmp_path)
    state = initial_state()
    started = store.start(state)
    assert started.changed is True
    assert store.start(state).changed is False
    goals = json.loads(store.paths(PLAN_ID).goals.read_text(encoding="utf-8"))
    assert [goal["goal_id"] for goal in goals["goals"]] == list(GOAL_IDS)
    assert [goal["status"] for goal in goals["goals"][:4]] == ["complete", "complete", "ready", "pending"]
    assert all(goal["plan_digest"] == PLAN_DIGEST for goal in goals["goals"])

    request = boundary_request(state)
    first = store.transition(PLAN_ID, request)
    assert first.changed is True
    assert first.state["generation"] == 1
    assert first.event["precondition_digest"] == state["state_hash"]
    assert first.event["operation_digest"] == request.operation_digest()
    assert first.event["state_patch"]["phase"] == "analyze"
    tampered_precondition = dict(first.event)
    tampered_precondition["precondition_digest"] = digest_value("different-before-state")
    tampered_precondition["event_hash"] = ""
    tampered_precondition["event_hash"] = event_hash(tampered_precondition)
    with pytest.raises(ValueError, match="precondition_digest"):
        validate_event(tampered_precondition)
    invalid_patch_type = dict(first.event)
    invalid_patch_type["state_patch"] = {**first.event["state_patch"], "phase": 99}
    invalid_patch_type["event_hash"] = ""
    invalid_patch_type["event_hash"] = event_hash(invalid_patch_type)
    with pytest.raises(ValueError, match="state_patch.phase"):
        validate_event(invalid_patch_type)
    invalid_risk = dict(first.event)
    invalid_risk["state_patch"] = {**first.event["state_patch"], "risk": "unbounded"}
    invalid_risk["event_hash"] = ""
    invalid_risk["event_hash"] = event_hash(invalid_risk)
    with pytest.raises(ValueError, match="state_patch.risk"):
        validate_event(invalid_risk)
    immutable_patch = dict(first.event)
    immutable_patch["state_patch"] = {**first.event["state_patch"], "boundary_epoch": 2}
    immutable_patch["event_hash"] = ""
    immutable_patch["event_hash"] = event_hash(immutable_patch)
    with pytest.raises(ValueError, match="immutable"):
        validate_event(immutable_patch)
    continued_start = store.start(state)
    assert continued_start.changed is False
    assert continued_start.state["generation"] == 1

    retry = store.transition(PLAN_ID, request)
    assert retry.changed is False
    assert retry.reason == "idempotent retry"
    conflicting = TransitionRequest(
        operation_id=request.operation_id,
        transition="BLOCK",
        expected_generation=0,
        reason="changed-operation",
    )
    with pytest.raises(ConvergentIdempotencyError):
        store.transition(PLAN_ID, conflicting)


def test_start_rejects_goal_artifact_tampering_and_wrong_valid_plan_digest(tmp_path: Path) -> None:
    _root, store = make_store(tmp_path)
    state = initial_state()
    store.start(state)
    paths = store.paths(PLAN_ID)
    artifact = json.loads(paths.goals.read_text(encoding="utf-8"))
    artifact["goals"][0]["status"] = "pending"
    paths.goals.write_text(json.dumps(artifact, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    paths.goals.chmod(0o600)
    with pytest.raises(ConvergentIntegrityError, match="deterministic compiler"):
        store.start(state)

    wrong = initial_state()
    wrong["plan_digest"] = "sha256:" + "0" * 64
    wrong["task_identity"]["plan_digest_hash"] = digest_value(wrong["plan_digest"])
    wrong["task_id"] = digest_value(wrong["task_identity"])
    wrong["state_hash"] = ""
    wrong["state_hash"] = state_hash(wrong)
    with pytest.raises(store_module.ConvergentStoreError, match="approved serial goal set"):
        store.start(wrong)


def test_atomic_start_and_prompt_classification_is_retry_safe(tmp_path: Path) -> None:
    _root, store = make_store(tmp_path)
    state = initial_state()
    request = boundary_request(state, operation_id="op-atomic-boundary")
    first = store.start_and_transition(state, request)
    assert first.changed is True
    assert first.state["phase"] == "analyze"
    assert first.state["generation"] == 1
    retry = store.start_and_transition(state, request)
    assert retry.changed is False
    assert retry.reason == "idempotent atomic start"
    assert store.read_current(PLAN_ID).state == first.state


def test_new_task_epoch_rotation_preserves_prior_state_and_publishes_cas_pointer(tmp_path: Path) -> None:
    _root, store = make_store(tmp_path)
    previous = initial_state()
    store.start(previous)

    identity = TaskIdentity.from_values(
        session="session-new",
        project="project-store",
        worktree="workspace-store",
        branch="codex/ralph-convergent-execution-v4",
        objective="A genuinely new work item",
        boundary_epoch=2,
        sensitivity="GREEN",
        plan=PLAN_ID,
        plan_version=1,
        plan_digest=PLAN_DIGEST,
    )
    candidate = new_state(
        policy=load_execution_policy(),
        plan_id=PLAN_ID,
        plan_version=1,
        plan_digest=PLAN_DIGEST,
        task_identity=identity,
        goal_id="G-BASELINE",
        task_epoch="epoch-new",
        boundary_epoch=2,
        boundary_kind="new_task",
        activation_mode="shadow",
    )
    evidence = LeaseEvidence(
        model="gpt-5.6-sol",
        reasoning_effort="max",
        tools=("apply_patch", "exec_command"),
        cwd=str(ROOT),
        branch="codex/ralph-convergent-execution-v4",
        task_epoch="epoch-new",
        owner_role="sol-worker",
        authority_role="codex-main",
        source="verified-runtime",
    )
    lease = acquire_execution_lease(evidence, policy=load_execution_policy(), issued_generation=0)
    request = TransitionRequest(
        operation_id="rotate-epoch-new",
        transition="BOUNDARY_CLASSIFIED",
        expected_generation=0,
        evidence_ids=("epoch-rotation",),
        lease=lease,
    )
    result = store.rotate_epoch_and_transition(candidate, request)
    assert result.state is not None and result.state["task_epoch"] == "epoch-new"
    paths = store.paths(PLAN_ID)
    pointer = json.loads(paths.active_epoch.read_text(encoding="utf-8"))
    assert pointer["epoch_id"] == "epoch-new"
    assert pointer["state_hash"] == result.state["state_hash"]
    assert list((paths.root / "epochs").iterdir())
    assert store.read_current(PLAN_ID, authoritative=True).state["task_epoch"] == "epoch-new"
    retry = store.rotate_epoch_and_transition(candidate, request)
    assert retry.changed is False
    assert retry.replayed is True


def test_pending_epoch_rotation_recovers_partial_archive_before_authoritative_read(tmp_path: Path) -> None:
    _root, store = make_store(tmp_path)
    store.start(initial_state())
    candidate, request = epoch_candidate("epoch-current", "current work", 2, "rotate-current")
    store.rotate_epoch_and_transition(candidate, request)
    paths = store.paths(PLAN_ID)
    current = store.read_current(PLAN_ID, authoritative=True).state
    assert current is not None

    archive_name = "prepared-recovery"
    archive = paths.root / "epochs" / archive_name
    archive.mkdir(mode=0o700)
    for name in store._epoch_movable_names():
        source = paths.root / name
        if source.exists():
            shutil.copy2(source, archive / name)
    paths.state.unlink()
    marker = {
        "schema_version": 1,
        "archive_name": archive_name,
        "candidate_epoch_id": "epoch-recovery",
        "candidate_task_id": "sha256:" + "c" * 64,
        "operation_id": "rotate-recovery",
        "operation_digest": digest_value("rotate-recovery"),
        "previous_state_hash": current["state_hash"],
        "files": list(store._epoch_movable_names()),
    }
    store_module.publish_json(paths.rotation_pending, marker, hard_limit=store_module.MAX_STATE_BYTES)

    recovered = store.read_current(PLAN_ID, authoritative=True)

    assert recovered.state == current
    assert not paths.rotation_pending.exists()
    assert not archive.exists()


def test_epoch_rotation_failure_after_pointer_publication_restores_previous_epoch_and_is_retryable(
    monkeypatch, tmp_path: Path
) -> None:
    _root, store = make_store(tmp_path)
    store.start(initial_state())
    first_candidate, first_request = epoch_candidate("epoch-first", "first work", 2, "rotate-first")
    store.rotate_epoch_and_transition(first_candidate, first_request)
    paths = store.paths(PLAN_ID)
    before = store.read_current(PLAN_ID, authoritative=True).state
    assert before is not None
    second_candidate, second_request = epoch_candidate("epoch-second", "second work", 3, "rotate-second")
    original_publish = store._publish_active_epoch

    def publish_then_fail(*args, **kwargs):
        original_publish(*args, **kwargs)
        raise RuntimeError("simulated crash after pointer publication")

    monkeypatch.setattr(store, "_publish_active_epoch", publish_then_fail)
    with pytest.raises(RuntimeError, match="simulated crash"):
        store.rotate_epoch_and_transition(second_candidate, second_request)

    restored = store.read_current(PLAN_ID, authoritative=True).state
    assert restored == before
    assert not paths.rotation_pending.exists()
    assert not (paths.root / "epochs" / str(second_candidate["task_id"]).replace(":", "-")).exists()

    monkeypatch.setattr(store, "_publish_active_epoch", original_publish)
    retried = store.rotate_epoch_and_transition(second_candidate, second_request)
    assert retried.state is not None and retried.state["task_epoch"] == "epoch-second"
    assert store.read_current(PLAN_ID, authoritative=True).state == retried.state


def test_start_compiles_registered_non_rollout_plan_from_active_metadata(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    progress = ImplementationStore(resolve_store_paths(primary_root=root))
    plan_id = "custom-plan-20260811"
    plan_bytes = b"# custom plan\n"
    plan_digest = "sha256:" + hashlib.sha256(plan_bytes).hexdigest()
    (root / ".ralph" / "plans").mkdir(parents=True)
    (root / ".ralph" / "plans" / "custom-plan.md").write_bytes(plan_bytes)
    progress.register_plan(
        plan_id,
        plan_path=".ralph/plans/custom-plan.md",
        objective="Validate a user-owned execution plan.",
        phase="verification",
        next_action="Run the bounded verification gates.",
        operation_id="op-register-custom",
    )
    identity = TaskIdentity.from_values(
        session="session-custom",
        project="project-custom",
        worktree="workspace-custom",
        branch="codex/custom-plan",
        objective="Validate a user-owned execution plan.",
        boundary_epoch=1,
        sensitivity="GREEN",
        plan=plan_id,
        plan_version=1,
        plan_digest=plan_digest,
    )
    state = new_state(
        policy=load_execution_policy(),
        plan_id=plan_id,
        plan_version=1,
        plan_digest=plan_digest,
        task_identity=identity,
        goal_id="G-CUSTOM",
        task_epoch="epoch-custom",
        boundary_epoch=1,
        boundary_kind="new_task",
        activation_mode="shadow",
    )
    custom_store = ConvergentStore(progress, load_execution_policy())
    started = custom_store.start(state)
    assert started.changed is True
    goals = json.loads(custom_store.paths(plan_id).goals.read_text(encoding="utf-8"))
    assert [goal["goal_id"] for goal in goals["goals"]] == ["G-CUSTOM"]
    assert goals["goals"][0]["objective"] == "Validate a user-owned execution plan."


def test_plan_provenance_rejects_oversized_plan_before_reading(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    progress = ImplementationStore(resolve_store_paths(primary_root=root))
    plan_id = "oversized-plan-20260811"
    plan_path = root / ".ralph" / "plans" / "oversized-plan.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_bytes(b"x" * (store_module.MAX_PLAN_BYTES + 1))
    progress.register_plan(plan_id, plan_path=".ralph/plans/oversized-plan.md", operation_id="op-register-oversized")
    store = ConvergentStore(progress, load_execution_policy())
    metadata = progress.read_state(plan_id)
    assert metadata is not None
    with pytest.raises(store_module.ConvergentStoreError, match="bounded size"):
        store._validate_plan_provenance({"plan_digest": "sha256:" + "0" * 64}, metadata)


def test_material_amendment_journal_is_append_only_idempotent_and_budgeted(tmp_path: Path) -> None:
    _root, store = make_store(tmp_path)
    amendment = DecisionAmendment.create(
        amendment_id="AMD-1",
        task_epoch="epoch-store",
        prior_decision_version=1,
        new_decision_version=2,
        prior_decision_fingerprint=digest_value("packet-v1"),
        new_evidence=("EV-new",),
        invalidated_assumption="The original API remains stable.",
        affected_invariants=("Public compatibility",),
        design_impact="Add a versioned adapter.",
        changed_steps=("S-1",),
        unchanged_steps=(),
        verification_changes=("Add compatibility coverage",),
        approval_required=True,
        new_decision_fingerprint=digest_value("packet-v2"),
    )
    with pytest.raises(store_module.ConvergentStoreError, match="not initialized"):
        store.append_amendment(PLAN_ID, amendment)

    amendable = initial_state()
    lease = boundary_request(amendable).lease
    assert lease is not None
    amendable["execution_lease"] = lease.as_dict()
    amendable["phase"] = "design_ready"
    amendable["aristotle"].update(
        {"tier": "quick", "decision_version": 1, "decision_fingerprint": digest_value("packet-v1")}
    )
    amendable["state_hash"] = ""
    amendable["state_hash"] = state_hash(amendable)
    store.start(amendable)
    with pytest.raises(store_module.ConvergentStoreError, match="DecisionAmendment contract"):
        store.append_amendment(PLAN_ID, amendment.as_dict())  # type: ignore[arg-type]
    assert store.append_amendment(PLAN_ID, amendment).changed is True
    assert store.append_amendment(PLAN_ID, amendment).changed is False
    approval = AmendmentApproval.create(
        amendment_id=amendment.amendment_id,
        task_epoch=amendment.task_epoch,
        prior_decision_version=amendment.prior_decision_version,
        new_decision_version=amendment.new_decision_version,
        amendment_fingerprint=amendment.amendment_fingerprint,
        actor_role="codex-main",
        approval_evidence_digest=digest_value("approved-by-user"),
    )
    assert store.append_amendment_approval(PLAN_ID, approval).changed is True
    assert store.append_amendment_approval(PLAN_ID, approval).changed is False
    conflicting = DecisionAmendment.create(
        amendment_id="AMD-1",
        task_epoch="epoch-store",
        prior_decision_version=1,
        new_decision_version=2,
        prior_decision_fingerprint=digest_value("packet-v1"),
        new_evidence=("EV-different",),
        invalidated_assumption="The original API remains stable.",
        affected_invariants=("Public compatibility",),
        design_impact="Use a different adapter.",
        changed_steps=("S-1",),
        unchanged_steps=(),
        verification_changes=("Add compatibility coverage",),
        approval_required=True,
        new_decision_fingerprint=digest_value("packet-v2"),
    )
    with pytest.raises(ConvergentIdempotencyError, match="amendment ID conflicts"):
        store.append_amendment(PLAN_ID, conflicting)
    second = DecisionAmendment.create(
        amendment_id="AMD-2",
        task_epoch="epoch-store",
        prior_decision_version=1,
        new_decision_version=2,
        prior_decision_fingerprint=digest_value("packet-v1"),
        new_evidence=("EV-second",),
        invalidated_assumption="A second assumption changed.",
        affected_invariants=("Scope stability",),
        design_impact="A second redesign would be required.",
        changed_steps=("S-2",),
        unchanged_steps=(),
        verification_changes=("Add another gate",),
        approval_required=True,
        new_decision_fingerprint=digest_value("packet-v3"),
    )
    with pytest.raises(store_module.ConvergentStoreError, match="USER_DECISION"):
        store.append_amendment(PLAN_ID, second)


def test_machine_artifacts_reject_nested_raw_and_red_material(tmp_path: Path) -> None:
    _root, store = make_store(tmp_path)
    with pytest.raises(store_module.ConvergentStoreError, match="not initialized"):
        store.publish_artifact(PLAN_ID, "findings", {"findings": []})
    store.start(initial_state())
    with pytest.raises(store_module.ConvergentStoreError, match="unsupported"):
        store.publish_artifact(PLAN_ID, "goals", {"goals": []})
    with pytest.raises(store_module.ConvergentStoreError, match="forbidden raw"):
        store.publish_artifact(
            PLAN_ID,
            "findings",
            {"findings": [{"evidence": {"reviewer_output": "unbounded prose"}}]},
        )
    with pytest.raises(store_module.ConvergentStoreError, match="forbidden raw"):
        store.publish_artifact(
            PLAN_ID,
            "findings",
            {"findings": [{"evidence": {"reviewerOutput": "unbounded prose"}}]},
        )
    with pytest.raises(store_module.ConvergentStoreError, match="RED material"):
        store.publish_artifact(
            PLAN_ID,
            "final-audit",
            {"checks": [{"label": "api_key" + "=fixture-value"}]},
        )


def test_machine_artifacts_are_immutable_after_close(tmp_path: Path) -> None:
    _root, store = make_store(tmp_path)
    closed = initial_state()
    closed["phase"] = "close"
    closed["status"] = "closed"
    closed["execution_lease"] = acquire_execution_lease(
        LeaseEvidence(
            model="gpt-5.6-sol",
            reasoning_effort="max",
            tools=("apply_patch", "exec_command"),
            cwd=str(ROOT),
            branch="codex/ralph-convergent-execution-v4",
            task_epoch="epoch-store",
            owner_role="sol-worker",
            authority_role="codex-main",
            source="verified-runtime",
        ),
        policy=load_execution_policy(),
        issued_generation=0,
    ).as_dict()
    closed["aristotle"]["tier"] = "full"
    closed["aristotle"]["decision_version"] = 1
    closed["aristotle"]["decision_fingerprint"] = digest_value("closed-packet")
    closed["completion"].update(
        {
            "hard_gates_pass": True,
            "handoff_published": True,
            "handoff_digest": digest_value("handoff"),
            "evidence_manifest_digest": digest_value("manifest"),
            "final_audit_digest": digest_value("audit"),
        }
    )
    closed["final_audit_digest"] = closed["completion"]["final_audit_digest"]
    closed["state_hash"] = state_hash(closed)
    store.start(closed)
    path = store.paths(PLAN_ID).findings
    path.write_text('{"sentinel":"prior"}\n', encoding="utf-8")
    with pytest.raises(store_module.ConvergentStoreError, match="immutable after close"):
        store.publish_artifact(PLAN_ID, "findings", {"findings": []})
    assert path.read_text(encoding="utf-8") == '{"sentinel":"prior"}\n'


def test_policy_drift_blocks_reads_replay_and_machine_artifact_mutation(tmp_path: Path) -> None:
    _root, store = make_store(tmp_path)
    store.start(initial_state())
    drifted_policy = replace(load_execution_policy(), policy_hash=digest_value("drifted-policy"))
    drifted = ConvergentStore(store.progress, drifted_policy)
    with pytest.raises(PolicyDriftError):
        drifted.read_current(PLAN_ID)
    with pytest.raises(PolicyDriftError):
        drifted.replay(PLAN_ID)
    with pytest.raises(PolicyDriftError):
        drifted.publish_artifact(PLAN_ID, "findings", {"findings": []})
    assert not drifted.paths(PLAN_ID).findings.exists()


def test_stale_cas_and_concurrent_same_operation_are_finite(tmp_path: Path) -> None:
    _root, store = make_store(tmp_path)
    state = initial_state()
    store.start(state)
    request = boundary_request(state, operation_id="op-concurrent")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: store.transition(PLAN_ID, request), range(2)))
    assert sum(result.changed for result in results) == 1
    assert {result.reason for result in results} == {"transition committed", "idempotent retry"}

    stale = TransitionRequest(operation_id="op-stale", transition="BLOCK", expected_generation=0, reason="stale")
    with pytest.raises(TransitionError, match="stale"):
        store.transition(PLAN_ID, stale)


def test_crash_after_journal_append_replays_exact_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _root, store = make_store(tmp_path)
    state = initial_state()
    store.start(state)
    request = boundary_request(state, operation_id="op-crash")
    real_publish = store_module.publish_json

    def crash_snapshot(path: Path, payload: dict, *, hard_limit: int):
        if path == store.paths(PLAN_ID).state:
            raise OSError("simulated crash after append")
        return real_publish(path, payload, hard_limit=hard_limit)

    monkeypatch.setattr(store_module, "publish_json", crash_snapshot)
    with pytest.raises(OSError, match="simulated crash"):
        store.transition(PLAN_ID, request)
    monkeypatch.setattr(store_module, "publish_json", real_publish)

    read_only = store.read_current(PLAN_ID)
    assert read_only.replayed is True
    assert read_only.state["generation"] == 1
    repaired = store.replay(PLAN_ID)
    assert repaired.changed is True
    assert store.read_current(PLAN_ID).replayed is False


def test_incomplete_tail_future_schema_and_out_of_order_events_block(tmp_path: Path) -> None:
    _root, store = make_store(tmp_path)
    state = initial_state()
    store.start(state)
    store.transition(PLAN_ID, boundary_request(state))
    paths = store.paths(PLAN_ID)

    with paths.events.open("ab") as handle:
        handle.write(b'{"incomplete":')
        handle.flush()
        os.fsync(handle.fileno())
    with pytest.raises(ConvergentIntegrityError, match="incomplete final line"):
        store.transition(
            PLAN_ID,
            TransitionRequest(operation_id="op-after-tail", transition="BLOCK", expected_generation=1, reason="blocked"),
        )

    # Restore the one complete event, then make it validly hashed but out of order.
    complete = paths.events.read_bytes().splitlines()[0]
    event = json.loads(complete.decode("utf-8"))
    event["sequence"] = 2
    event["event_hash"] = event_hash(event)
    paths.events.write_text(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    paths.events.chmod(0o600)
    with pytest.raises(ConvergentIntegrityError, match="out of order"):
        store.read_current(PLAN_ID)

    # State future schemas are never quarantined or downgraded.
    snapshot = json.loads(paths.state.read_text(encoding="utf-8"))
    snapshot["schema_version"] = 99
    paths.state.write_text(json.dumps(snapshot, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    paths.state.chmod(0o600)
    with pytest.raises(FutureExecutionSchemaError):
        store.read_current(PLAN_ID)
    assert paths.state.exists()
    assert not list(paths.root.glob("state.invalid.*"))
