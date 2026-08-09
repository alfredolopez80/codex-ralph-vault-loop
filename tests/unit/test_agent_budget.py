from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.agent_budget import (
    MAX_DEPTH,
    MAX_PACKET_BYTES,
    MAX_TASK_ADVISORS,
    MAX_TASK_JOBS,
    MAX_THREADS,
    bounded_packet,
    budget_decision,
    normalize_ledger,
    packet_bytes,
    record_failure,
    record_spawn,
    task_signature,
)
from shared.sol_advisor import initialize, read_state, reserve_worker_spawn, state_path
from shared.subagent_routing import (
    LUNA_DEFAULT_EFFORT,
    LUNA_MODEL,
    SOL_MODEL,
    ExecutorDefaults,
    RoutingRequest,
    resolve_subagent_routing,
)


def resolve(**changes: object):
    values: dict[str, object] = {
        "repository_default": ExecutorDefaults(LUNA_MODEL, LUNA_DEFAULT_EFFORT),
        "raw_complexity": 1,
        "intent": "routine",
    }
    values.update(changes)
    return resolve_subagent_routing(RoutingRequest(**values))


def test_platform_and_task_ceiling_are_two_threads_and_one_depth() -> None:
    assert MAX_THREADS == 2
    assert MAX_DEPTH == 1
    assert MAX_TASK_JOBS == 2


def test_complexity_bands_do_not_fan_out_without_structured_evidence() -> None:
    assert resolve(raw_complexity=2, intent="implementation").subagent_route == "none"
    assert resolve(raw_complexity=5, intent="implementation").subagent_route == "none"
    assert resolve(raw_complexity=7, intent="routine").subagent_route == "none"
    assert resolve(raw_complexity=7, intent="architecture").subagent_route == "sol-advisor"


def test_independent_measurable_block_is_required_for_a_worker() -> None:
    decision = resolve(raw_complexity=5, intent="implementation", independent_block=True)

    assert decision.subagent_route == "terra-implementation"
    assert decision.spawn_required is True
    assert decision.max_threads == 2
    assert decision.max_depth == 1


def test_sol_executor_does_not_receive_routine_sol_self_supervision() -> None:
    executor = ExecutorDefaults("GPT_5.6_SOL/xhigh", "xhigh")
    suppressed = resolve(
        raw_complexity=9,
        intent="security",
        repository_default=executor,
    )
    critical = resolve(
        raw_complexity=9,
        intent="security",
        repository_default=executor,
        critical_review=True,
    )

    assert suppressed.subagent_route == "none"
    assert suppressed.reason_code == "sol-self-supervision-suppressed"
    assert critical.subagent_route == "sol-advisor"


def test_sol_executor_may_use_one_independent_terra_worker() -> None:
    executor = ExecutorDefaults("gpt-5.6-sol", "xhigh")
    decision = resolve(
        raw_complexity=9,
        intent="implementation",
        repository_default=executor,
        independent_block=True,
    )

    assert decision.subagent_route == "terra-implementation"


def test_first_failure_stays_local_and_two_distinct_failures_may_escalate() -> None:
    first = resolve(
        raw_complexity=9,
        intent="debugging",
        failure_fingerprints=("failure-a",),
    )
    second = resolve(
        raw_complexity=9,
        intent="debugging",
        failure_fingerprints=("failure-a", "failure-b"),
    )
    repeated = resolve(
        raw_complexity=9,
        intent="debugging",
        failure_fingerprints=("failure-a", "failure-a"),
    )

    assert first.subagent_route == "none"
    assert first.reason_code == "inspect-first-failure-locally"
    assert second.subagent_route == "sol-advisor"
    assert repeated.subagent_route == "none"


def test_red_and_depth_limits_fail_closed_for_optional_delegation() -> None:
    red = budget_decision({}, kind="advisor", sensitivity="RED")
    depth = budget_decision({}, kind="worker", depth=1, independent=True)

    assert red.allowed is False and red.reason == "red-local-only"
    assert depth.allowed is False and depth.reason == "max-depth-reached"


def test_task_signature_is_content_free_and_scoped_to_workspace_branch_and_prompt() -> None:
    base = {
        "project_id": "fixture-project",
        "workspace_identity": "/tmp/workspace-a",
        "branch": "feature/a",
        "model": "gpt-5.6-luna",
        "session_id": "session-a",
    }
    first = task_signature(base, prompt="Implement the bounded worker policy")
    branch = task_signature({**base, "branch": "feature/b"}, prompt="Implement the bounded worker policy")
    prompt = task_signature(base, prompt="Implement a different bounded worker policy")

    assert first != branch
    assert first != prompt
    assert "Implement" not in first
    assert len(first) == 24

    assert first != task_signature({**base, "sensitivity": "RED"}, prompt="Implement the bounded worker policy")


def test_ledger_is_bounded_and_contains_no_content() -> None:
    raw_prompt = "DO NOT PERSIST THIS PROMPT"
    ledger = normalize_ledger(
        {
            "task_signature": "task-hash",
            "agents_started": 100,
            "reasons": ["reason"] * 100,
            "failure_fingerprints": ["failure"] * 100,
            "bytes_sent": 999_999,
        }
    )
    ledger = record_failure(ledger, "failure-new")
    ledger = record_spawn(ledger, kind="worker", reason="independent-block", bytes_sent=12)

    encoded = json.dumps(ledger, sort_keys=True)
    assert ledger["agents_started"] <= MAX_TASK_JOBS
    assert ledger["advisors_started"] <= MAX_TASK_ADVISORS
    assert len(ledger["reasons"]) <= 8
    assert len(ledger["failure_fingerprints"]) <= 8
    assert raw_prompt not in encoded


def test_advisor_packet_has_required_contract_and_hard_cap() -> None:
    packet = bounded_packet(
        question="Choose one option",
        context="x" * 20_000,
        files=["src/a.py"] * 100,
        constraints="keep RED local",
        budget_bytes=MAX_PACKET_BYTES,
    )

    assert set(packet) == {"question", "context", "files", "constraints", "output_format", "budget_bytes"}
    assert packet_bytes(packet) <= MAX_PACKET_BYTES
    assert packet["files"]


def test_packet_hard_cap_applies_to_all_untrusted_fields() -> None:
    packet = bounded_packet(
        question="question " * 2_000,
        context="context " * 8_000,
        files=["/tmp/relevant.py"] * 20,
        constraints="constraint " * 2_000,
        budget_bytes=256,
    )

    assert packet_bytes(packet) <= 256
    assert set(packet) >= {"question", "context", "files", "constraints", "output_format", "budget_bytes"}


def test_concurrent_worker_reservations_are_capped_and_scoped(tmp_path: Path, monkeypatch) -> None:
    state_root = tmp_path / "state"
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(state_root))
    event = {
        "cwd": str(ROOT),
        "session_id": "budget-race",
        "complexity": 5,
        "intent": "implementation",
        "independent_block": True,
        "prompt": "Implement an independent measurable block.",
    }
    state = initialize(event)
    assert state is not None
    spawn_arguments = dict(state["routing"]["spawn_arguments"])

    def reserve(index: int) -> bool:
        return reserve_worker_spawn(
            {
                **event,
                "tool_name": "spawn_agent",
                "tool_input": {
                    **spawn_arguments,
                    "invocation_id": f"worker-{index}",
                    "message": f"Implement independent bounded block {index}.",
                },
            }
        )[0]

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(reserve, range(4)))

    assert sum(results) == MAX_TASK_JOBS
    state = read_state(event)
    assert state["agent_budget"]["reserved_jobs"] == MAX_TASK_JOBS
    assert state_path(event).read_text(encoding="utf-8").find("Implement an independent") == -1
