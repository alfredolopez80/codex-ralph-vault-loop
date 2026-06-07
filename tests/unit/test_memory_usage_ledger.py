from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MEMORY_DIR = ROOT / "scripts" / "memory"
if str(MEMORY_DIR) not in sys.path:
    sys.path.insert(0, str(MEMORY_DIR))

import usage_ledger  # noqa: E402
from recall_v2 import context_for, recall  # noqa: E402
from tree_store import TreeStore  # noqa: E402

LEDGER = ROOT / "scripts" / "memory" / "usage_ledger.py"
PROJECT = "p-ledger-test"


def red_text() -> str:
    return "tok" + "en=abcd1234"


def write_sample(tmp_path: Path, query: str = "find alpha") -> bool:
    return usage_ledger.record_usage(
        tmp_path,
        PROJECT,
        query=query,
        branch="main",
        session_id="session-ledger",
        engine="tree",
        selected_memory_ids=["node_alpha"],
        rejected=[{"node_id": "node_beta", "reason": "wrong_project"}],
        fallback_used=False,
        shadow_enabled=True,
        raw_recommended=True,
        raw_opened=False,
        raw_included=False,
        token_budget_used=7,
        token_budget_limit=99,
        latency_ms=3,
    )


def ledger_path(tmp_path: Path) -> Path:
    return usage_ledger.usage_path(tmp_path, PROJECT)


def test_write_valid_jsonl(tmp_path: Path) -> None:
    assert write_sample(tmp_path)

    lines = ledger_path(tmp_path).read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[-1])

    assert event["schema_version"] == usage_ledger.SCHEMA_VERSION
    assert event["engine"] == "tree"
    assert event["query_hash"] == usage_ledger.query_hash("find alpha")
    assert event["selected_memory_ids"] == ["node_alpha"]
    assert event["rejected_reason_counts"] == {"wrong_project": 1}
    assert event["raw_included"] is False


def test_concurrent_writes_preserve_events(tmp_path: Path) -> None:
    failures: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            ok = usage_ledger.record_usage(
                tmp_path,
                PROJECT,
                query=f"query {index}",
                selected_memory_ids=[f"node_{index}"],
                rejected=[],
            )
            assert ok
        except BaseException as exc:  # pragma: no cover - re-raised below
            failures.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if failures:
        raise failures[0]

    events = [json.loads(line) for line in ledger_path(tmp_path).read_text(encoding="utf-8").splitlines()]
    selected = {event["selected_memory_ids"][0] for event in events}

    assert len(events) == 12
    assert selected == {f"node_{index}" for index in range(12)}


def test_no_raw_prompt_text_or_raw_memory_stored(tmp_path: Path) -> None:
    raw_prompt = "exact private phrase that should never be stored"
    raw_memory = "raw memory body should never be stored"

    usage_ledger.record_usage(
        tmp_path,
        PROJECT,
        query=raw_prompt,
        selected_memory_ids=[raw_memory],
        rejected=[{"node_id": raw_memory, "reason": "no_match"}],
    )
    text = ledger_path(tmp_path).read_text(encoding="utf-8")

    assert raw_prompt not in text
    assert raw_memory not in text
    assert usage_ledger.query_hash(raw_prompt) in text


def test_red_like_input_is_sanitized_or_skipped(tmp_path: Path) -> None:
    sensitive = red_text()

    usage_ledger.record_usage(
        tmp_path,
        PROJECT,
        query=sensitive,
        selected_memory_ids=[sensitive],
        rejected=[{"node_id": sensitive, "reason": sensitive}],
    )
    text = ledger_path(tmp_path).read_text(encoding="utf-8")
    event = json.loads(text.splitlines()[-1])

    assert sensitive not in text
    assert event["selected_memory_ids"][0].startswith("id_hash_")
    assert event["rejected_reason_counts"]


def test_corrupt_line_handled_safely(tmp_path: Path) -> None:
    assert write_sample(tmp_path)
    path = ledger_path(tmp_path)
    path.write_text("not json\n" + path.read_text(encoding="utf-8"), encoding="utf-8")

    events = usage_ledger.iter_events(path)

    assert len(events) == 1
    assert events[0]["selected_memory_ids"] == ["node_alpha"]


def test_summary_command_works(tmp_path: Path) -> None:
    assert write_sample(tmp_path)

    result = subprocess.run(
        [sys.executable, str(LEDGER), "--project-id", PROJECT, "--ralph-home", str(tmp_path), "--project-root", str(tmp_path), "--summary"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["event_count"] == 1
    assert summary["engine_counts"] == {"tree": 1}
    assert summary["shadow_count"] == 1
    assert summary["raw_included_count"] == 0


def test_tail_command_works(tmp_path: Path) -> None:
    assert write_sample(tmp_path, "first query")
    assert write_sample(tmp_path, "second query")

    result = subprocess.run(
        [sys.executable, str(LEDGER), "--project-id", PROJECT, "--ralph-home", str(tmp_path), "--project-root", str(tmp_path), "--tail", "1"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    events = json.loads(result.stdout)
    assert len(events) == 1
    assert events[0]["query_hash"] == usage_ledger.query_hash("second query")


def test_ledger_write_failure_fails_open(monkeypatch, tmp_path: Path) -> None:
    def fail_append(*_args, **_kwargs):
        raise OSError("cannot write")

    monkeypatch.setattr(usage_ledger, "append_jsonl", fail_append)

    assert usage_ledger.record_usage(tmp_path, PROJECT, query="safe query") is False


def test_ledger_path_symlink_fails_open_without_write_through(tmp_path: Path) -> None:
    path = ledger_path(tmp_path)
    external = tmp_path / "outside.jsonl"
    external.write_text("", encoding="utf-8")
    path.unlink()
    path.symlink_to(external)

    assert usage_ledger.record_usage(tmp_path, PROJECT, query="safe query") is False
    assert external.read_text(encoding="utf-8") == ""


def test_existing_ledger_permissions_are_restricted(tmp_path: Path) -> None:
    path = ledger_path(tmp_path)
    path.chmod(0o644)

    assert usage_ledger.record_usage(tmp_path, PROJECT, query="safe query") is True

    assert path.stat().st_mode & 0o777 == 0o600


def test_ledger_path_hardlink_fails_open_without_write_through(tmp_path: Path) -> None:
    path = ledger_path(tmp_path)
    external = tmp_path / "outside-hardlink.jsonl"
    external.write_text("", encoding="utf-8")
    external.chmod(0o644)
    path.unlink()
    os.link(external, path)

    assert usage_ledger.record_usage(tmp_path, PROJECT, query="safe query") is False
    assert external.read_text(encoding="utf-8") == ""
    assert external.stat().st_mode & 0o777 == 0o644


def test_query_hash_deterministic() -> None:
    assert usage_ledger.query_hash("alpha   beta") == usage_ledger.query_hash("alpha beta")
    assert usage_ledger.query_hash("alpha beta") != usage_ledger.query_hash("alpha gamma")


def test_recall_v2_writes_privacy_safe_usage_event(tmp_path: Path) -> None:
    context = context_for(tmp_path, PROJECT, "main")
    TreeStore(tmp_path).create_node(
        {
            "schema_version": "ralph_memory_node_v2",
            "node_id": "node_recall_ledger",
            "project_id": PROJECT,
            "workspace_instance_id": context.workspace_instance_id,
            "repo_remote_hash": "remotehash",
            "branch": "main",
            "commit": "abc123",
            "session_id": "session-ledger",
            "memory_type": "fact",
            "sensitivity": "YELLOW",
            "authority": "non_authoritative",
            "summary": "Ledger integration marker.",
            "detailed_summary": "Raw-looking details stay outside usage events.",
            "trigger": {"terms": ["ledger-integration"]},
            "topic_tags": ["ledger"],
            "entities": ["Ledger"],
            "source_paths": ["docs/ledger.md"],
            "raw_ref": None,
            "links": [],
            "salience": {"validation": 0.5},
            "quality": {"confidence": 0.8, "provenance_complete": True, "stale": False, "deprecated": False},
            "created_at": "2026-06-07T00:00:00+00:00",
            "updated_at": "2026-06-07T00:00:00+00:00",
            "compaction_reason": "ledger_test",
        }
    )
    query = "ledger-integration private prompt phrase"

    report = recall(query, context, tmp_path)
    text = ledger_path(tmp_path).read_text(encoding="utf-8")

    assert report["MEMORY_TRACE_JSON"]["selected_memory_ids"] == ["node_recall_ledger"]
    assert query not in text
    assert "Ledger integration marker" not in text
    assert usage_ledger.query_hash(query) in text
