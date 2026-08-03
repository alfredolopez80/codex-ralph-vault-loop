from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "scripts" / "plans"
if str(PLANS) not in sys.path:
    sys.path.insert(0, str(PLANS))

import implementation_index_lib as index_lib
from implementation_index_lib import (
    append_event,
    append_note_and_refresh,
    load_index,
    record_loose_commit,
    refresh_notes_metadata,
    render_markdown,
    upsert_plan_entry,
)
from implementation_notes_lib import ImplementationNotesError, Roots, entry_html, html_document


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# fixture\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "init")
    return repo


def test_load_index_starts_empty_without_writing(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    data = load_index(repo)

    assert data["version"] == 2
    assert data["canonical_repo_root"] == str(repo.resolve())
    assert data["plans"] == []
    assert data["loose_commits"] == []
    assert data["events"] == []
    assert not (repo / ".ralph" / "plans" / "implementation-index.json").exists()
    assert not (repo / ".ralph" / "plans" / "implementation-index.lock").exists()


def test_upsert_plan_entry_dedupes_commits_and_renders_index(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    plan = repo / ".ralph" / "plans" / "feature.md"
    notes = repo / ".ralph" / "plans" / "feature-implementation-notes.html"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Feature\n", encoding="utf-8")
    notes.write_text("<main data-implementation-notes=\"true\"></main>\n", encoding="utf-8")
    commit = git(repo, "rev-parse", "HEAD")

    first = upsert_plan_entry(
        primary_root=repo,
        plan_path=plan,
        notes_path=notes,
        status="active",
        active_root=repo,
        commit=commit,
        branch="main",
        pr="https://example.invalid/pr/1",
        session_id="session-1",
    )
    second = upsert_plan_entry(
        primary_root=repo,
        plan_path=plan,
        notes_path=notes,
        status="implemented",
        active_root=repo,
        commit=commit,
        branch="main",
    )

    assert first["plan"] == ".ralph/plans/feature.md"
    assert second["status"] == "implemented"
    data = json.loads((repo / ".ralph" / "plans" / "implementation-index.json").read_text(encoding="utf-8"))
    assert len(data["plans"]) == 1
    assert data["plans"][0]["commits"] == [commit]
    assert [event["event"] for event in data["events"]] == ["notes_created", "implemented"]
    assert all(event["event_id"] for event in data["events"])
    assert all(event["timestamp"] == event["created_at"] for event in data["events"])
    rendered = (repo / ".ralph" / "plans" / "implementation-index.md").read_text(encoding="utf-8")
    assert "[.ralph/plans/feature.md](.ralph/plans/feature.md)" in rendered
    assert "https://example.invalid/pr/1" in rendered
    assert "Implementation Events" in rendered


def test_repeated_lifecycle_event_is_deduplicated(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    plan = repo / ".ralph" / "plans" / "feature.md"
    notes = repo / ".ralph" / "plans" / "feature-implementation-notes.html"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Feature\n", encoding="utf-8")
    notes.write_text('<main data-implementation-notes="true"></main>\n', encoding="utf-8")

    for _ in range(2):
        upsert_plan_entry(
            primary_root=repo,
            plan_path=plan,
            notes_path=notes,
            status="active",
            active_root=repo,
            branch="main",
            session_id="same-session",
            event="plan_updated",
        )

    data = json.loads((repo / ".ralph" / "plans" / "implementation-index.json").read_text(encoding="utf-8"))
    assert len(data["events"]) == 1
    assert data["events"][0]["event"] == "plan_updated"


def test_record_loose_commit_updates_existing_entry_and_rejects_red(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    commit = git(repo, "rev-parse", "HEAD")

    record_loose_commit(
        primary_root=repo,
        commit=commit,
        active_root=repo,
        reason="hotfix without approved plan",
        branch="main",
        notes="initial note",
    )
    record_loose_commit(
        primary_root=repo,
        commit=commit,
        active_root=repo,
        reason="updated reason",
        branch="main",
        notes="updated note",
    )

    data = json.loads((repo / ".ralph" / "plans" / "implementation-index.json").read_text(encoding="utf-8"))
    assert len(data["loose_commits"]) == 1
    assert data["loose_commits"][0]["reason"] == "updated reason"
    assert data["loose_commits"][0]["linked_plan"] is None
    try:
        record_loose_commit(primary_root=repo, commit=commit, active_root=repo, reason="token=abc123")
    except ImplementationNotesError as exc:
        assert "RED-sensitive" in str(exc)
    else:
        raise AssertionError("expected RED-sensitive loose commit reason to be rejected")


def test_concurrent_plan_updates_preserve_distinct_events(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    plan = repo / ".ralph" / "plans" / "concurrent.md"
    notes = repo / ".ralph" / "plans" / "concurrent-implementation-notes.html"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Concurrent\n", encoding="utf-8")
    notes.write_text('<main data-implementation-notes="true"></main>\n', encoding="utf-8")
    runner = (
        "import sys; from pathlib import Path; "
        "sys.path.insert(0, sys.argv[2]); "
        "from implementation_index_lib import upsert_plan_entry; "
        "root=Path(sys.argv[1]); plan=root/'.ralph/plans/concurrent.md'; "
        "notes=root/'.ralph/plans/concurrent-implementation-notes.html'; "
        "upsert_plan_entry(primary_root=root, plan_path=plan, notes_path=notes, "
        "status='active', active_root=root, branch='main', session_id=sys.argv[3], event='plan_updated')"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PLANS)
    processes = [
        subprocess.Popen([sys.executable, "-c", runner, str(repo), str(PLANS), f"session-{index}"], cwd=ROOT, env=env)
        for index in range(2)
    ]
    assert all(process.wait(timeout=15) == 0 for process in processes)

    data = json.loads((repo / ".ralph" / "plans" / "implementation-index.json").read_text(encoding="utf-8"))
    assert len(data["plans"]) == 1
    assert {event["session_id"] for event in data["events"]} == {"session-0", "session-1"}
    assert len({event["event_id"] for event in data["events"]}) == 2


def test_corrupt_index_is_quarantined_before_recovery(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    index_dir = repo / ".ralph" / "plans"
    index_dir.mkdir(parents=True)
    index_path = index_dir / "implementation-index.json"
    index_path.write_text("{not-json\n", encoding="utf-8")

    data = load_index(repo)

    assert data["plans"] == []
    assert not index_path.exists()
    quarantined = list(index_dir.glob("implementation-index.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "{not-json\n"


def test_corrupt_index_recovery_serializes_quarantine_across_readers(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    index_dir = repo / ".ralph" / "plans"
    index_dir.mkdir(parents=True)
    index_path = index_dir / "implementation-index.json"
    index_path.write_text("{not-json\n", encoding="utf-8")
    runner = """
import sys
import time
from pathlib import Path
import implementation_index_lib as lib

original = lib._quarantine_corrupt_index
def delayed(path):
    time.sleep(0.05)
    return original(path)
lib._quarantine_corrupt_index = delayed
lib.load_index(Path(sys.argv[1]))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PLANS)
    processes = [
        subprocess.Popen([sys.executable, "-c", runner, str(repo)], cwd=ROOT, env=env)
        for _ in range(8)
    ]
    assert all(process.wait(timeout=15) == 0 for process in processes)
    assert not index_path.exists()
    quarantined = list(index_dir.glob("implementation-index.json.corrupt-*"))
    assert len(quarantined) == 1


def test_index_lock_rejects_symlink_and_hardlink_aliases(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    index_dir = repo / ".ralph" / "plans"
    index_dir.mkdir(parents=True)
    index_path = index_dir / "implementation-index.json"
    index_path.write_text(json.dumps(index_lib.empty_index(repo)), encoding="utf-8")
    lock_path = index_dir / "implementation-index.lock"

    lock_path.symlink_to(index_path)
    with pytest.raises(ImplementationNotesError, match="lock cannot be a symlink"):
        load_index(repo)
    lock_path.unlink()

    lock_path.hardlink_to(index_path)
    with pytest.raises(ImplementationNotesError, match="lock must not be hard-linked"):
        load_index(repo)


def test_malformed_nested_index_shape_is_quarantined(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    index_dir = repo / ".ralph" / "plans"
    index_dir.mkdir(parents=True)
    index_path = index_dir / "implementation-index.json"
    index_path.write_text(
        json.dumps(
            {
                "version": 2,
                "plans": [{"plan": ".ralph/plans/bad.md", "commits": None}],
                "loose_commits": [],
                "events": [],
            }
        ),
        encoding="utf-8",
    )

    data = load_index(repo)

    assert data["plans"] == []
    quarantined = list(index_dir.glob("implementation-index.json.corrupt-*"))
    assert len(quarantined) == 1


def test_future_index_version_is_rejected_without_overwrite(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    index_dir = repo / ".ralph" / "plans"
    index_dir.mkdir(parents=True)
    index_path = index_dir / "implementation-index.json"
    index_path.write_text(
        json.dumps({"version": 99, "plans": [], "loose_commits": [], "events": []}),
        encoding="utf-8",
    )

    original = index_path.read_bytes()
    with pytest.raises(ImplementationNotesError, match="newer than supported"):
        load_index(repo)

    plan = index_dir / "future.md"
    notes = index_dir / "future-implementation-notes.html"
    plan.write_text("# Future\n", encoding="utf-8")
    notes.write_text('<main data-implementation-notes="true"></main>\n', encoding="utf-8")
    with pytest.raises(ImplementationNotesError, match="newer than supported"):
        upsert_plan_entry(primary_root=repo, plan_path=plan, notes_path=notes, status="active", active_root=repo)

    assert index_path.read_bytes() == original
    assert not list(index_dir.glob("implementation-index.json.corrupt-*"))


def test_atomic_replacement_preserves_existing_index_modes(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    plan = repo / ".ralph" / "plans" / "mode.md"
    notes = repo / ".ralph" / "plans" / "mode-implementation-notes.html"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Mode\n", encoding="utf-8")
    notes.write_text('<main data-implementation-notes="true"></main>\n', encoding="utf-8")
    upsert_plan_entry(primary_root=repo, plan_path=plan, notes_path=notes, status="active", active_root=repo)
    index_json = repo / ".ralph" / "plans" / "implementation-index.json"
    index_md = repo / ".ralph" / "plans" / "implementation-index.md"
    index_json.chmod(0o640)
    index_md.chmod(0o640)

    upsert_plan_entry(primary_root=repo, plan_path=plan, notes_path=notes, status="implemented", active_root=repo)

    assert stat.S_IMODE(index_json.stat().st_mode) == 0o640
    assert stat.S_IMODE(index_md.stat().st_mode) == 0o640


def test_refresh_uses_current_invocation_provenance(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    plan = repo / ".ralph" / "plans" / "provenance.md"
    notes = repo / ".ralph" / "plans" / "provenance-implementation-notes.html"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Provenance\n", encoding="utf-8")
    notes.write_text('<main data-implementation-notes="true"></main>\n', encoding="utf-8")
    upsert_plan_entry(
        primary_root=repo,
        plan_path=plan,
        notes_path=notes,
        status="active",
        active_root=repo,
        branch="branch-a",
        session_id="session-a",
    )

    refresh_notes_metadata(
        primary_root=repo,
        notes_path=notes,
        active_root=repo,
        branch="branch-b",
        session_id="session-b",
        commit=git(repo, "rev-parse", "HEAD"),
    )

    data = json.loads((repo / ".ralph" / "plans" / "implementation-index.json").read_text(encoding="utf-8"))
    event = data["events"][-1]
    assert event["event"] == "note_appended"
    assert event["branch"] == "branch-b"
    assert event["session_id"] == "session-b"

    refresh_notes_metadata(
        primary_root=repo,
        notes_path=notes,
        active_root=repo,
        branch="branch-c",
        session_id="",
        commit=git(repo, "rev-parse", "HEAD"),
    )
    data = json.loads((repo / ".ralph" / "plans" / "implementation-index.json").read_text(encoding="utf-8"))
    assert data["plans"][0]["session_id"] == "session-b"


def test_distinct_operation_ids_survive_same_second_deduplication(tmp_path: Path, monkeypatch) -> None:
    repo = make_repo(tmp_path)
    data = index_lib.empty_index(repo)
    monkeypatch.setattr(index_lib, "now_local", lambda: "2026-08-03T12:00:00+00:00")

    append_event(
        data,
        event="note_appended",
        primary_root=repo,
        active_root=repo,
        operation_id="operation-a",
    )
    append_event(
        data,
        event="note_appended",
        primary_root=repo,
        active_root=repo,
        operation_id="operation-b",
    )

    assert len(data["events"]) == 2
    assert {event["operation_id"] for event in data["events"]} == {"operation-a", "operation-b"}


def test_same_operation_id_is_scoped_to_plan_and_notes_resource(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    data = index_lib.empty_index(repo)

    for name in ("a", "b"):
        append_event(
            data,
            event="note_appended",
            primary_root=repo,
            active_root=repo,
            plan_path=repo / ".ralph" / "plans" / f"{name}.md",
            notes_path=repo / ".ralph" / "plans" / f"{name}-implementation-notes.html",
            operation_id="shared-operation",
        )

    assert len(data["events"]) == 2
    assert {event["plan"] for event in data["events"]} == {
        ".ralph/plans/a.md",
        ".ralph/plans/b.md",
    }


def test_replayed_operation_id_remains_single_note_after_later_append(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    plan = repo / ".ralph" / "plans" / "replay.md"
    notes = repo / ".ralph" / "plans" / "replay-implementation-notes.html"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Replay\n", encoding="utf-8")
    notes.write_text(
        html_document(
            title="Replay",
            plan_path=plan,
            notes_path=notes,
            roots=Roots(repo, repo, repo / ".git", "test"),
            git_sha=git(repo, "rev-parse", "HEAD"),
            git_branch="main",
            session_id="session-replay",
            timestamp="2026-08-03T11:59:00+00:00",
        ),
        encoding="utf-8",
    )
    upsert_plan_entry(primary_root=repo, plan_path=plan, notes_path=notes, status="active", active_root=repo)

    def append(operation_id: str, decision: str) -> None:
        append_note_and_refresh(
            primary_root=repo,
            notes_path=notes,
            entry_html_text=entry_html(
                category="decision",
                decision=decision,
                reason="retry identity must be stable",
                impact="one durable note per operation",
                related_files=[str(plan)],
                status="active",
                timestamp="2026-08-03T12:00:00+00:00",
                operation_id=operation_id,
            ),
            category="decision",
            active_root=repo,
            session_id="session-replay",
            operation_id=operation_id,
        )

    append("operation-a", "first")
    append("operation-b", "later")
    append("operation-a", "first")

    with pytest.raises(ImplementationNotesError, match="different note payload"):
        append("operation-a", "conflicting replay")

    html = notes.read_text(encoding="utf-8")
    assert html.count("<dt>Operation ID</dt><dd>operation-a</dd>") == 1
    data = json.loads((repo / ".ralph" / "plans" / "implementation-index.json").read_text(encoding="utf-8"))
    assert [event.get("operation_id") for event in data["events"] if event.get("event") == "note_appended"].count("operation-a") == 1


def test_v1_index_is_preserved_on_first_v2_write(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    index_dir = repo / ".ralph" / "plans"
    index_dir.mkdir(parents=True)
    legacy_plan = {"plan": ".ralph/plans/legacy.md", "status": "active"}
    legacy_commit = {"commit": "legacy-sha", "reason": "legacy record"}
    (index_dir / "implementation-index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "canonical_repo_root": str(repo),
                "plans": [legacy_plan],
                "loose_commits": [legacy_commit],
            }
        ),
        encoding="utf-8",
    )
    plan = index_dir / "new.md"
    notes = index_dir / "new-implementation-notes.html"
    plan.write_text("# New\n", encoding="utf-8")
    notes.write_text('<main data-implementation-notes="true"></main>\n', encoding="utf-8")

    upsert_plan_entry(primary_root=repo, plan_path=plan, notes_path=notes, status="active", active_root=repo)

    migrated = json.loads((index_dir / "implementation-index.json").read_text(encoding="utf-8"))
    assert migrated["version"] == 2
    assert legacy_plan in migrated["plans"]
    assert legacy_commit in migrated["loose_commits"]
    assert migrated["events"]


def test_note_append_recovers_after_index_write_interruption(tmp_path: Path, monkeypatch) -> None:
    repo = make_repo(tmp_path)
    plan = repo / ".ralph" / "plans" / "recover.md"
    notes = repo / ".ralph" / "plans" / "recover-implementation-notes.html"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Recover\n", encoding="utf-8")
    notes.write_text(
        html_document(
            title="Recover",
            plan_path=plan,
            notes_path=notes,
            roots=Roots(repo, repo, repo / ".git", "test"),
            git_sha=git(repo, "rev-parse", "HEAD"),
            git_branch="main",
            session_id="session-recover",
            timestamp="2026-08-03T11:59:00+00:00",
        ),
        encoding="utf-8",
    )
    upsert_plan_entry(primary_root=repo, plan_path=plan, notes_path=notes, status="active", active_root=repo)
    note = entry_html(
        category="decision",
        decision="Recover after an interrupted index write.",
        reason="The note is durable before the process can finish the index transaction.",
        impact="A later lifecycle operation must reconcile the operation exactly once.",
        related_files=[str(plan)],
        status="active",
        timestamp="2026-08-03T12:00:00+00:00",
        operation_id="recover-1",
    )
    original_write = index_lib._write_index_unlocked
    monkeypatch.setattr(index_lib, "_write_index_unlocked", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("interrupt")))
    try:
        append_note_and_refresh(
            primary_root=repo,
            notes_path=notes,
            entry_html_text=note,
            category="decision",
            active_root=repo,
            session_id="session-recover",
            operation_id="recover-1",
        )
    except RuntimeError as exc:
        assert str(exc) == "interrupt"
    else:
        raise AssertionError("expected simulated index interruption")
    monkeypatch.setattr(index_lib, "_write_index_unlocked", original_write)

    upsert_plan_entry(primary_root=repo, plan_path=plan, notes_path=notes, status="implemented", active_root=repo)
    data = json.loads((repo / ".ralph" / "plans" / "implementation-index.json").read_text(encoding="utf-8"))
    recovered = [event for event in data["events"] if event.get("operation_id") == "recover-1"]
    assert len(recovered) == 1


def test_concurrent_note_appends_preserve_each_operation(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    plan = repo / ".ralph" / "plans" / "concurrent-notes.md"
    notes = repo / ".ralph" / "plans" / "concurrent-notes-implementation-notes.html"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Concurrent notes\n", encoding="utf-8")
    notes.write_text(
        html_document(
            title="Concurrent notes",
            plan_path=plan,
            notes_path=notes,
            roots=Roots(repo, repo, repo / ".git", "test"),
            git_sha=git(repo, "rev-parse", "HEAD"),
            git_branch="main",
            session_id="session-0",
            timestamp="2026-08-03T11:59:00+00:00",
        ),
        encoding="utf-8",
    )
    upsert_plan_entry(primary_root=repo, plan_path=plan, notes_path=notes, status="active", active_root=repo)
    runner = """
import sys
from pathlib import Path
from implementation_index_lib import append_note_and_refresh
from implementation_notes_lib import entry_html
root = Path(sys.argv[1])
plan = root / '.ralph/plans/concurrent-notes.md'
notes = root / '.ralph/plans/concurrent-notes-implementation-notes.html'
operation = sys.argv[2]
entry = entry_html(
    category='decision', decision=f'decision-{operation}', reason='concurrent append',
    impact='each operation remains durable', related_files=[str(plan)], status='active',
    timestamp='2026-08-03T12:00:00+00:00', operation_id=operation,
)
append_note_and_refresh(
    primary_root=root, notes_path=notes, entry_html_text=entry, category='decision',
    active_root=root, session_id=operation, operation_id=operation,
)
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PLANS)
    processes = [
        subprocess.Popen([sys.executable, "-c", runner, str(repo), operation], cwd=ROOT, env=env)
        for operation in ("operation-a", "operation-b")
    ]
    assert all(process.wait(timeout=15) == 0 for process in processes)
    html = notes.read_text(encoding="utf-8")
    assert html.count("<dt>Operation ID</dt><dd>operation-") == 2
    data = json.loads((repo / ".ralph" / "plans" / "implementation-index.json").read_text(encoding="utf-8"))
    assert {event.get("operation_id") for event in data["events"] if event.get("event") == "note_appended"} == {
        "operation-a",
        "operation-b",
    }


def test_render_markdown_escapes_table_cells() -> None:
    rendered = render_markdown(
        {
            "canonical_repo_root": "/repo",
            "updated_at": "2026-05-23T00:00:00Z",
            "plans": [
                {
                    "status": "implemented",
                    "plan": ".ralph/plans/a|b.md",
                    "notes": ".ralph/plans/a.html",
                    "branch": "feature|branch",
                    "commits": ["abc123"],
                    "pr": "line\nbreak",
                    "updated_at": "now",
                }
            ],
            "loose_commits": [
                {
                    "commit": "def456",
                    "branch": "main",
                    "reason": "fix | reason",
                    "notes": "multi\nline",
                    "updated_at": "later",
                }
            ],
        }
    )

    assert "a\\|b.md" in rendered
    assert "`feature\\|branch`" in rendered
    assert "line break" in rendered
    assert "fix \\| reason" in rendered
    assert "multi line" in rendered
