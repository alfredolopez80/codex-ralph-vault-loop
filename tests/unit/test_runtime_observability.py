from __future__ import annotations

import importlib.util
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.active_context import active_context_from_payload
from shared.runtime_observability import (
    EVENTS,
    SCHEMA_NAME,
    SCHEMA_VERSION,
    append_event,
    build_event,
    event_path,
    normalize_event,
    record_event,
)


REPORTER = ROOT / "scripts" / "evals" / "report_runtime_overhead.py"
spec = importlib.util.spec_from_file_location("runtime_overhead_reporter", REPORTER)
assert spec and spec.loader
reporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reporter)


def _payload(tmp_path: Path) -> dict[str, object]:
    return {"cwd": str(tmp_path), "session_id": "session-a", "turn_id": "turn-a", "model": "gpt-5.6-luna"}


def _event(tmp_path: Path, *, event: str = "post_tool", duration_ns: int = 10_000_000, scenario: str = "small") -> dict[str, object]:
    payload = _payload(tmp_path)
    context = active_context_from_payload(payload, resolve_git=False)
    built = build_event(
        context=context,
        payload=payload,
        event=event,
        dispatcher="test_dispatcher",
        duration_ns=duration_ns,
        process_count=1,
        child_process_count=0,
        output_bytes=40,
        estimated_context_units=10,
        persistence_bytes=7,
        continuation_count=1 if event == "stop" else 0,
        advisor_count=1 if event == "subagent" else 0,
        scenario=scenario,
        success=True,
    )
    assert built is not None
    return built


def test_schema_is_versioned_and_content_free(tmp_path: Path) -> None:
    event = _event(tmp_path)
    assert event["schema_version"] == SCHEMA_VERSION
    assert event["schema_name"] == SCHEMA_NAME
    assert event["model_family"] == "luna"
    assert event["model_source"] == "payload"
    assert event["model_verified"] is True
    assert set(EVENTS) == {"session_start", "user_prompt", "pre_tool", "post_tool", "stop", "subagent", "maintenance"}
    assert event["subscription_usage_measured"] is False
    assert "session-a" not in json.dumps(event)
    assert normalize_event({**event, "model_source": "private-selector"})["model_source"] == "unknown"
    assert normalize_event({**event, "prompt": "private text"}) is None
    assert normalize_event({**event, "tool_response": "private result"}) is None


def test_writer_is_atomic_under_concurrent_writes(tmp_path: Path, monkeypatch) -> None:
    runtime = tmp_path / "runtime"
    monkeypatch.setenv("RALPH_HOME", str(runtime))
    context_payload = _payload(tmp_path)
    context = active_context_from_payload(context_payload, resolve_git=False)
    event = _event(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: append_event(context, event), range(24)))
    assert all(results)
    lines = event_path(context.project_id).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 24
    assert all(json.loads(line)["schema_name"] == SCHEMA_NAME for line in lines)


def test_record_event_hashes_safe_ids_exactly_once(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "runtime"))
    payload = _payload(tmp_path)
    context = active_context_from_payload(payload, resolve_git=False)
    expected = _event(tmp_path)
    assert record_event(
        context,
        payload,
        event="post_tool",
        dispatcher="test_dispatcher",
        duration_ns=1,
        process_count=1,
    )
    stored = json.loads(event_path(context.project_id).read_text(encoding="utf-8").splitlines()[0])
    assert stored["session_id"] == expected["session_id"]
    assert stored["turn_id"] == expected["turn_id"]
    assert stored["task_signature"] == expected["task_signature"]


def test_rotation_is_bounded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "runtime"))
    monkeypatch.setenv("RALPH_RUNTIME_EVENTS_MAX_BYTES", "32768")
    monkeypatch.setenv("RALPH_RUNTIME_EVENTS_MAX_FILES", "3")
    context = active_context_from_payload(_payload(tmp_path), resolve_git=False)
    event = _event(tmp_path)
    for _ in range(160):
        assert append_event(context, event)
    files = list(event_path(context.project_id).parent.glob("runtime-events.jsonl*"))
    assert len(files) <= 3
    assert all(item.stat().st_size <= 32768 or item.name != "runtime-events.jsonl" for item in files)


def test_reporter_math_corruption_and_maintenance(tmp_path: Path) -> None:
    source = tmp_path / "events.jsonl"
    records = [_event(tmp_path, duration_ns=value, event="post_tool") for value in (10_000_000, 20_000_000, 40_000_000)]
    records.append(_event(tmp_path, duration_ns=90_000_000, event="maintenance", scenario="backlog"))
    source.write_text("\n".join(json.dumps(record, sort_keys=True) for record in records) + "\nnot-json\n", encoding="utf-8")
    quarantine = tmp_path / "quarantine.jsonl"
    loaded, stats = reporter.read_jsonl([source], quarantine_path=quarantine)
    assert len(loaded) == 4
    assert stats["corrupt"] == 1
    assert "not-json" not in quarantine.read_text(encoding="utf-8")
    report = reporter.build_report(loaded, stats)
    assert report["interactive"]["runtime_p50_ms"] == 20.0
    assert report["interactive"]["runtime_p95_ms"] == 40.0
    assert report["maintenance_deferred"]["runtime_p95_ms"] == 90.0
    assert report["subscription_usage_measured"] is False
    assert "credits" in " ".join(report["limitations"])


def test_reporter_empty_input_has_no_divide_by_zero() -> None:
    report = reporter.build_report([])
    assert report["interactive"]["count"] == 0
    assert report["interactive"]["runtime_p50_ms"] is None
    assert report["confidence"]["level"] == "low"


def test_optional_user_usage_is_separate_and_unverified(tmp_path: Path) -> None:
    usage = tmp_path / "usage.csv"
    usage.write_text("timestamp,usage_units\n2026-08-08T20:00:00Z,12\nambiguous,8\n", encoding="utf-8")
    result = reporter.load_user_usage(usage)
    assert result == {
        "source": "user_supplied_usage",
        "verified": False,
        "rows_accepted": 1,
        "rows_rejected": 0,
        "ambiguous_rows": 1,
        "usage_units_total": 12.0,
        "subscription_usage_measured": False,
    }


def test_report_is_deterministic(tmp_path: Path) -> None:
    records = [_event(tmp_path, duration_ns=20_000_000, scenario="deterministic")]
    first = reporter.markdown_report(reporter.build_report(records))
    second = reporter.markdown_report(reporter.build_report(records))
    assert first == second
