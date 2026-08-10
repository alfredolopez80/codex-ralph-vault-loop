from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "plans" / "progress.py"


def git(cwd: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def run_cli(root: Path, *args: str, session: str = "") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if session:
        env["CODEX_SESSION_ID"] = session
    return subprocess.run([sys.executable, str(CLI), *args], cwd=root, env=env, text=True, capture_output=True, check=False)


def json_result(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert result.stdout, result.stderr
    return json.loads(result.stdout)


def repo(tmp_path: Path, name: str = "demo") -> tuple[Path, Path]:
    root = tmp_path / name
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Context Test")
    (root / "README.md").write_text("# fixture\n", encoding="utf-8")
    git(root, "add", "README.md")
    git(root, "commit", "-qm", "fixture")
    plan = root / ".ralph" / "plans" / f"{name}.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Context fixture\n", encoding="utf-8")
    return root, plan


def context(root: Path, plan: Path, *, event: str, session: str, epoch: str, **extra: str) -> dict[str, object]:
    args = [
        "context",
        "--plan",
        str(plan),
        "--profile",
        "luna",
        "--event",
        event,
        "--session-id",
        session,
        "--context-epoch",
        epoch,
        "--format",
        "json",
    ]
    for key, value in extra.items():
        flag = f"--{key.replace('_', '-')}"
        if value == "true":
            args.append(flag)
        else:
            args.extend([flag, value])
    result = run_cli(root, *args)
    assert result.returncode == 0, result.stderr
    return json_result(result)


def test_context_epochs_and_ledger_are_exactly_once_across_subprocesses(tmp_path: Path) -> None:
    root, plan = repo(tmp_path)
    started = run_cli(root, "start", "--plan", str(plan), "--operation-id", "start", "--format", "json", session="starter")
    assert started.returncode == 0, started.stderr
    ledger = root / ".local-notes" / "ralph" / "implementation" / "context-emissions.jsonl"

    ordinary = context(root, plan, event="ordinary", session="session-a", epoch="ordinary-1")
    assert ordinary["emitted"] is False
    assert not ledger.exists()

    startup = context(root, plan, event="startup", session="session-a", epoch="startup-1")
    assert startup["emitted"] is True and startup["capsule_kind"] == "full"
    before = (ledger.read_bytes(), ledger.stat().st_mtime_ns)
    retry = context(root, plan, event="startup", session="session-a", epoch="startup-1")
    assert retry["emitted"] is False and retry["ledger_hit"] is True
    assert (ledger.read_bytes(), ledger.stat().st_mtime_ns) == before

    session_b = context(root, plan, event="startup", session="session-b", epoch="startup-b")
    assert session_b["emitted"] is True and session_b["capsule_kind"] == "full"

    updated = run_cli(
        root,
        "record",
        "--plan",
        str(plan),
        "--kind",
        "decision",
        "--summary",
        "External writer changed the generation.",
        "--operation-id",
        "decision-1",
        "--format",
        "json",
        session="writer-b",
    )
    assert updated.returncode == 0, updated.stderr
    same_writer = context(root, plan, event="resume", session="writer-b", epoch="resume-writer")
    assert same_writer["emitted"] is False and same_writer["reason"] == "same_session_writer"

    delta = context(root, plan, event="external", session="session-a", epoch="resume-a", external_writer="true")
    assert delta["emitted"] is True and delta["capsule_kind"] == "delta"

    compact = context(root, plan, event="compact", session="session-a", epoch="compact-a")
    assert compact["emitted"] is True and compact["capsule_kind"] == "full"
    compact_retry = context(root, plan, event="compact", session="session-a", epoch="compact-a")
    assert compact_retry["emitted"] is False and compact_retry["ledger_hit"] is True

    explicit = context(root, plan, event="explicit", session="session-a", epoch="explicit-a")
    assert explicit["emitted"] is True and explicit["capsule_kind"] == "expanded"
    unknown = context(root, plan, event="resume", session="unknown", epoch="unknown-resume")
    assert unknown["emitted"] is False and unknown["reason"] == "unknown_session"


def test_context_uses_one_legacy_recovery_source_when_new_state_is_missing(tmp_path: Path) -> None:
    root, plan = repo(tmp_path, name="legacy")
    # Build a valid historical source without registering a new-store plan.
    sys.path.insert(0, str(ROOT / "scripts" / "plans"))
    from implementation_notes_lib import Roots, append_entry, entry_html, html_document

    notes = plan.with_name(f"{plan.stem}-implementation-notes.html")
    notes.write_text(
        html_document(
            title="Implementation Notes - Legacy",
            plan_path=plan,
            notes_path=notes,
            roots=Roots(root, root),
            git_sha="abc1234",
            git_branch="main",
            session_id="legacy-writer",
            timestamp="2026-08-10T00:00:00+00:00",
        ),
        encoding="utf-8",
    )
    append_entry(
        notes,
        entry_html(
            category="decision",
            decision="Legacy recovery remains bounded.",
            reason="The new state is not present.",
            impact="Use the fallback once.",
            related_files=[],
            status="active",
            timestamp="2026-08-10T00:01:00+00:00",
        ),
        "decision",
    )
    recovered = context(root, plan, event="startup", session="fresh", epoch="legacy-start")
    assert recovered["emitted"] is True
    assert recovered["source"] == "legacy"
    assert recovered["fallback_used"] is True
    assert recovered["capsule_kind"] == "full"
    assert str(root) not in str(recovered["capsule"])
