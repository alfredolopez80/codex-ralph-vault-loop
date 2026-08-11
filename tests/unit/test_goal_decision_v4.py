from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.decision_packet import DecisionAmendment, DecisionPacket, DecisionPacketError  # noqa: E402
from shared.convergent_contracts import digest_value  # noqa: E402
from shared.convergent_aristotle import AristotleContractError, select_aristotle_tier, validate_aristotle_output  # noqa: E402
from shared.execution_policy import load_execution_policy  # noqa: E402
from shared.goal_compiler import GOAL_IDS, PLAN_ID, GoalCompileError, compile_goals, validate_goal  # noqa: E402


PLAN_DIGEST = "sha256:fead6e85227c68c863fa23ccccc30f559c3893ced514704f5643c61d1c41b5e1"


def test_tiered_aristotle_is_deterministic_and_critical_domains_win() -> None:
    policy = load_execution_policy()
    cases = (
        (1, "low", (), "micro", False),
        (3, "low", (), "quick", False),
        (4, "low", (), "full", True),
        (2, "material", (), "full", True),
        (1, "low", ("security",), "critical", True),
        (1, "critical", (), "critical", True),
    )
    for complexity, risk, domains, tier, packet_required in cases:
        first = select_aristotle_tier(
            complexity=complexity,
            risk=risk,
            critical_domains=domains,
            policy=policy,
        )
        second = select_aristotle_tier(
            complexity=complexity,
            risk=risk,
            critical_domains=domains,
            policy=policy,
        )
        assert first.tier == tier
        assert first.produces_decision_packet is packet_required
        assert first.decision_digest == second.decision_digest
        output: dict[str, object] = {section: "bounded evidence" for section in first.required_sections}
        if packet_required:
            output["decision_packet"] = DecisionPacket.create(**packet_values()).as_dict()
        validate_aristotle_output(first, output)

    with pytest.raises(AristotleContractError, match="unsupported"):
        select_aristotle_tier(complexity=2, risk="low", critical_domains=("billing",), policy=policy)
    decision = select_aristotle_tier(complexity=4, risk="material", policy=policy)
    with pytest.raises(AristotleContractError, match="missing"):
        validate_aristotle_output(decision, {"selected_move": "incomplete"})
    micro = select_aristotle_tier(complexity=1, risk="low", policy=policy)
    red_output = {section: "bounded evidence" for section in micro.required_sections}
    red_output["assumption"] = "api_key" + "=fixture-value"
    with pytest.raises(AristotleContractError, match="RED"):
        validate_aristotle_output(micro, red_output)

    whitespace_output = {section: "   \n\t" for section in micro.required_sections}
    with pytest.raises(AristotleContractError, match="empty"):
        validate_aristotle_output(micro, whitespace_output)


def packet_values() -> dict[str, object]:
    return {
        "decision_version": 1,
        "task_epoch": "epoch-1",
        "objective": "Implement the bounded convergent execution core.",
        "source_of_truth": ["Approved plan", "Supplied execution policy"],
        "assumptions": [
            {"id": "A-1", "statement": "The canonical plan store is available.", "evidence_refs": ["EV-plan"]}
        ],
        "irreducible_truths": [
            {"id": "T-1", "statement": "Raw prompts cannot enter the execution journal.", "evidence_refs": ["EV-policy"]}
        ],
        "root_cause": "Execution phases previously lacked one closed state contract.",
        "invariants": ["Codex main retains authority", "SOL max owns bounded implementation"],
        "selected_solution": "Reuse the implementation store IO in a private execution namespace.",
        "rejected_alternatives": ["Create another human progress store"],
        "affected_components": ["Hook shared runtime", "Implementation store namespace"],
        "implementation_sequence": [
            {
                "step_id": "S-1",
                "goal_id": "G-DECISION",
                "preconditions": ["Policy hash verified"],
                "outputs": ["Reducer", "Replayable journal"],
            }
        ],
        "verification_matrix": [
            {
                "gate": "unit",
                "command": "pytest focused v4 tests",
                "expected": "All focused tests pass",
                "evidence_path": "tests/unit/test_convergent_store_v4.py",
                "blocking": True,
            }
        ],
        "review_requirement": {"required": True, "risk": "critical", "owner": "reviewer", "max_passes": 1},
        "security_and_rollout": {
            "threat_boundaries": ["RED remains local"],
            "rollout": ["Shadow before enforce"],
            "observability": ["Content-free hashes and counters only"],
        },
        "rollback": {
            "triggers": ["Canary hard gate fails"],
            "steps": ["Disable the feature flag"],
            "preserve": ["Journals and evidence"],
        },
        "done_when": ["Replay and CAS tests pass"],
        "material_change_triggers": ["Policy hash changes", "Trust boundary changes"],
    }


def test_decision_packet_is_deterministic_nested_and_tamper_evident() -> None:
    first = DecisionPacket.create(**packet_values())
    second = DecisionPacket.create(**packet_values())
    assert first.analysis_fingerprint == second.analysis_fingerprint
    assert first.as_dict()["irreducible_truths"][0]["id"] == "T-1"
    assert first.as_dict()["implementation_sequence"][0]["goal_id"] == "G-DECISION"
    assert first.as_dict()["verification_matrix"][0]["blocking"] is True

    restored = DecisionPacket.from_mapping(first.as_dict())
    assert restored.analysis_fingerprint == first.analysis_fingerprint
    tampered = first.as_dict()
    tampered["selected_solution"] = "A changed solution"
    with pytest.raises(DecisionPacketError, match="fingerprint mismatch"):
        DecisionPacket.from_mapping(tampered)

    with pytest.raises(TypeError):
        first.assumptions[0]["statement"] = "mutable"  # type: ignore[index]
    with pytest.raises(TypeError):
        first.assumptions[0]["evidence_refs"][0] = "mutable"  # type: ignore[index]
    exported = first.as_dict()
    exported["assumptions"][0]["evidence_refs"][0] = "changed"
    assert first.as_dict()["assumptions"][0]["evidence_refs"] == ["EV-plan"]


def test_packet_review_budget_and_unknown_keys_fail_closed() -> None:
    values = packet_values()
    values["review_requirement"] = {"required": True, "risk": "low", "owner": "reviewer", "max_passes": 1}
    with pytest.raises(DecisionPacketError, match="0/1 risk budget"):
        DecisionPacket.create(**values)

    values = packet_values()
    values["miscellaneous"] = "scope"
    with pytest.raises(DecisionPacketError, match="key mismatch"):
        DecisionPacket.create(**values)


def test_material_amendment_is_deterministic_and_append_only_shaped() -> None:
    packet = DecisionPacket.create(**packet_values())
    amendment = DecisionAmendment.create(
        amendment_id="AMD-1",
        prior_decision_fingerprint=packet.analysis_fingerprint,
        new_evidence=["EV-new"],
        invalidated_assumption="The original API shape is stable.",
        affected_invariants=["Public contract compatibility"],
        design_impact="Add a versioned adapter.",
        changed_steps=["S-1"],
        unchanged_steps=["S-2"],
        verification_changes=["Add compatibility gate"],
        approval_required=True,
        new_decision_fingerprint=digest_value("packet-v2"),
    )
    assert amendment.new_fingerprint.startswith("sha256:")
    assert amendment.prior_packet_fingerprint == packet.analysis_fingerprint
    assert amendment.new_decision_fingerprint == digest_value("packet-v2")
    assert DecisionAmendment.from_mapping(amendment.as_dict()) == amendment
    tampered = amendment.as_dict()
    tampered["design_impact"] = "Different impact"
    with pytest.raises(DecisionPacketError, match="fingerprint mismatch"):
        DecisionAmendment.from_mapping(tampered)
    with pytest.raises(DecisionPacketError, match="sha256"):
        DecisionAmendment.create(
            amendment_id="AMD-bad-digest",
            prior_decision_fingerprint="sha256:" + "z" * 64,
            new_evidence=["EV-new"],
            invalidated_assumption="The original API shape is stable.",
            affected_invariants=["Public contract compatibility"],
            design_impact="Add a versioned adapter.",
            changed_steps=["S-1"],
            unchanged_steps=[],
            verification_changes=["Add compatibility gate"],
            approval_required=True,
            new_decision_fingerprint=digest_value("packet-v2"),
        )


def test_goal_compiler_uses_exact_serial_ids_scope_and_owner() -> None:
    first = compile_goals(
        plan_id=PLAN_ID,
        plan_version=1,
        plan_digest=PLAN_DIGEST,
        state_generation=7,
    )
    second = compile_goals(
        plan_id=PLAN_ID,
        plan_version=1,
        plan_digest=PLAN_DIGEST,
        state_generation=7,
    )
    assert tuple(goal.goal_id for goal in first) == GOAL_IDS
    assert tuple(goal.goal_digest for goal in first) == tuple(goal.goal_digest for goal in second)
    assert first[0].status == "ready"
    assert all(goal.status == "pending" for goal in first[1:])
    assert first[0].owner["authority"] == "codex-main"
    assert first[0].owner["implementation"] == "sol-worker"
    assert first[0].owner["model"] == "gpt-5.6-sol"
    assert first[0].owner["reasoning_effort"] == "max"
    assert all(goal.done_when and goal.required_evidence and goal.allowed_paths for goal in first)
    with pytest.raises(TypeError):
        first[0].owner["model"] = "alternate"  # type: ignore[index]
    with pytest.raises(GoalCompileError, match="approved deterministic template"):
        validate_goal(replace(first[0], objective="Invented miscellaneous scope"))

    continued = compile_goals(
        plan_id=PLAN_ID,
        plan_version=1,
        plan_digest=PLAN_DIGEST,
        state_generation=8,
        completed=GOAL_IDS[:2],
    )
    assert [goal.status for goal in continued[:4]] == ["complete", "complete", "ready", "pending"]


def test_goal_compiler_rejects_filename_id_bad_digest_and_nonserial_completion() -> None:
    with pytest.raises(GoalCompileError, match="logical plan"):
        compile_goals(
            plan_id="2026-08-11-ralph-convergent-execution-v4",
            plan_version=1,
            plan_digest=PLAN_DIGEST,
            state_generation=0,
        )
    with pytest.raises(GoalCompileError, match="sha256"):
        compile_goals(plan_id=PLAN_ID, plan_version=1, plan_digest="bad", state_generation=0)
    with pytest.raises(GoalCompileError, match="immutable approved plan"):
        compile_goals(
            plan_id=PLAN_ID,
            plan_version=1,
            plan_digest="sha256:" + "0" * 64,
            state_generation=0,
        )
    with pytest.raises(GoalCompileError, match="serial prefix"):
        compile_goals(
            plan_id=PLAN_ID,
            plan_version=1,
            plan_digest=PLAN_DIGEST,
            state_generation=0,
            completed=(GOAL_IDS[1],),
        )
    with pytest.raises(GoalCompileError, match="duplicate"):
        compile_goals(
            plan_id=PLAN_ID,
            plan_version=1,
            plan_digest=PLAN_DIGEST,
            state_generation=0,
            completed=(GOAL_IDS[0], GOAL_IDS[0]),
        )
