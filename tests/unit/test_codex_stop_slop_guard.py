from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "gates" / "codex_stop_slop_guard.py"


def load_module():
    spec = importlib.util.spec_from_file_location("codex_stop_slop_guard", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_classifies_short_message_as_short_skip() -> None:
    guard = load_module()
    classification = guard.classify_response("Done.")

    assert classification.mode == "short_skip"
    assert guard.pre_analyzer_decision(guard.parse_policy_config({}), classification).policy_action == "skip"


def test_classifies_oversize_message_as_oversize_skip() -> None:
    guard = load_module()
    classification = guard.classify_response("word " * 13_000)

    assert classification.mode == "oversize_skip"


def test_classifies_narrative_prose_as_prose_blocking() -> None:
    guard = load_module()
    text = (
        "The hook should still review normal final prose because the response is meant to be read as an "
        "explanation, not executed as a command packet or parsed as structured output."
    )

    assert guard.classify_response(text).mode == "prose_blocking"


def test_bulleted_explanatory_report_remains_prose_blocking() -> None:
    guard = load_module()
    text = """The validation found two concrete outcomes that matter.

- The prose path still needs a strict threshold.
- The operational path should not be scored as prose.

This remains an explanatory answer rather than a prompt to paste into Codex."""

    assert guard.classify_response(text).mode == "prose_blocking"


def test_goal_prompt_is_operational_skip() -> None:
    guard = load_module()
    text = """/goal Implement the approved hook plan.

Objective: update the Stop hook policy.
Constraints: do not install global hooks.
Validation: run the hook contract tests.
Done when: operational prompts do not block."""

    assert guard.classify_response(text).mode == "operational_skip"


def test_explanatory_prose_that_mentions_goal_stays_prose_blocking() -> None:
    guard = load_module()
    text = (
        "Codex can use /goal for bounded objectives, but this answer is explanatory prose about the "
        "routing tradeoff and should still be checked as prose when it is long enough."
    )

    assert guard.classify_response(text).mode == "prose_blocking"


def test_copy_prompt_into_codex_is_operational_skip() -> None:
    guard = load_module()
    text = "Copy this prompt into Codex and execute the listed validation steps after reading the approved plan."

    assert guard.classify_response(text).mode == "operational_skip"


def test_structured_outputs_are_skipped() -> None:
    guard = load_module()
    cases = [
        ('{"mode":"structured_skip","blocked":false,"items":["one","two","three","four","five","six","seven","eight"]}', "json_like"),
        ("mode: structured_skip\nblocked: false\nthreshold: 60\nreason: config", "yaml_like"),
        ("| file | result |\n| --- | --- |\n| hook.py | pass |", "table_like_line_count"),
        ("python3 -m pytest tests/unit/test_codex_stop_slop_guard.py -q\nbash .codex/tests/run-hook-tests.sh\n"
         "git status --short", "command_like_line_count"),
    ]

    for text, feature in cases:
        classification = guard.classify_response(text)
        assert classification.mode == "structured_skip"
        assert getattr(classification.features, feature)


def test_ambiguous_mixed_answer_defaults_to_prose_blocking() -> None:
    guard = load_module()
    text = (
        "I checked scripts/gates/codex_stop_slop_guard.py and the important behavior is still prose. "
        "There is one command to run later, but the current answer is an explanation of the tradeoff."
    )

    assert guard.classify_response(text).mode == "prose_blocking"


def test_policy_config_defaults_and_clamps() -> None:
    guard = load_module()

    assert guard.parse_policy_config({}).threshold == 60
    assert guard.parse_policy_config({"CODEX_SLOP_GUARD_THRESHOLD": "wat"}).threshold == 60
    assert guard.parse_policy_config({"CODEX_SLOP_GUARD_THRESHOLD": "-1"}).threshold == 0
    assert guard.parse_policy_config({"CODEX_SLOP_GUARD_THRESHOLD": "101"}).threshold == 100
    assert not guard.parse_policy_config({"CODEX_SLOP_GUARD_ENABLED": "0"}).enabled


def test_unsupported_mode_values_fall_back_to_defaults() -> None:
    guard = load_module()
    config = guard.parse_policy_config(
        {
            "CODEX_SLOP_GUARD_PROSE_MODE": "loud",
            "CODEX_SLOP_GUARD_OPERATIONAL_MODE": "warn",
            "CODEX_SLOP_GUARD_STRUCTURED_MODE": "print",
        }
    )

    assert config.prose_action == "block"
    assert config.operational_action == "skip"
    assert config.structured_action == "skip"


def test_prose_threshold_decision_blocks_only_below_floor() -> None:
    guard = load_module()
    config = guard.parse_policy_config({})
    classification = guard.classify_response(
        "This is normal narrative prose that should still be scored by the analyzer before finalization."
    )

    assert guard.post_analyzer_decision(config, classification, {"score": 59}).should_block
    assert not guard.post_analyzer_decision(config, classification, {"score": 60}).should_block


def test_skip_modes_do_not_run_analyzer() -> None:
    guard = load_module()
    config = guard.parse_policy_config({})

    for text in [
        "/goal Execute the approved plan with validation and report the result.",
        '{"result":"structured","blocked":false,"threshold":60}',
    ]:
        decision = guard.pre_analyzer_decision(config, guard.classify_response(text))
        assert decision.policy_action == "skip"
        assert not decision.should_run_analyzer


def test_advisory_action_never_blocks() -> None:
    guard = load_module()
    config = guard.parse_policy_config({"CODEX_SLOP_GUARD_PROSE_MODE": "advisory"})
    classification = guard.classify_response(
        "This prose is intentionally long enough to reach analyzer scoring in advisory mode."
    )
    decision = guard.post_analyzer_decision(config, classification, {"score": 0})

    assert decision.policy_action == "advisory"
    assert not decision.should_block


def test_analyzer_environment_excludes_secret_like_keys() -> None:
    guard = load_module()
    env = guard.analyzer_environment(
        {
            "PATH": "/bin",
            "HOME": "/tmp/home",
            "OPENAI_API_KEY": "secret",
            "SERVICE_TOKEN": "secret",
            "NORMAL": "ignored",
        }
    )

    assert env == {"PATH": "/bin", "HOME": "/tmp/home"}


def test_log_record_contains_schema_v2_and_no_raw_text() -> None:
    guard = load_module()
    secret_message = "This message contains secret_like_fixture_value and must never be logged in durable hook records."
    classification = guard.classify_response(secret_message)
    decision = guard.pre_analyzer_decision(guard.parse_policy_config({}), classification)
    raw_cwd = str(ROOT)
    record = guard.build_log_record(
        hook_input={"cwd": raw_cwd},
        config=guard.parse_policy_config({}),
        classification=classification,
        decision=decision,
        score=None,
        band=None,
        blocked=False,
        reason=decision.reason,
    )
    serialized = json.dumps(record)

    assert record["schema_version"] == 2
    assert record["event"] == "codex_stop_slop_guard"
    assert record["mode"] == "prose_blocking"
    assert record["threshold"] == 60
    assert len(record["message_sha256"]) == 64
    assert str(record["cwd"]).startswith("sha256:")
    assert "secret_like_fixture_value" not in serialized
    assert raw_cwd not in serialized


def test_real_hook_operational_skip_writes_log_without_analyzer(tmp_path: Path) -> None:
    payload = {
        "hook_event_name": "Stop",
        "session_id": "unit-real-operational",
        "cwd": str(ROOT),
        "last_assistant_message": "/goal Implement the hook policy and validate the results before finalizing.",
    }
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["PATH"] = ""

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    log_path = tmp_path / ".ralph-codex" / "logs" / "slop_guard_hooks.jsonl"
    row = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert row["mode"] == "operational_skip"
    assert row["policy_action"] == "skip"
    assert row["blocked"] is False
    assert row["score"] is None
