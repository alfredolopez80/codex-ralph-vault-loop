from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "scripts" / "plans"
if str(PLANS) not in sys.path:
    sys.path.insert(0, str(PLANS))

from implementation_context import select_implementation_context

CREATE = PLANS / "create-implementation-notes.py"
APPEND = PLANS / "append-implementation-note.py"
READER = PLANS / "read-implementation-context.py"
CONTINUITY = ROOT / ".codex" / "hooks" / "continuity_prompt_context.py"
WAKEUP = ROOT / "scripts" / "memory" / "wakeup.py"


def run(command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False)


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def fixture_repo(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, str]]:
    primary = tmp_path / "primary" / "sample-project"
    active = tmp_path / "home" / ".codex" / "worktrees" / "fixture" / "sample-project"
    primary.mkdir(parents=True)
    git(primary, "init")
    git(primary, "config", "user.email", "test@example.invalid")
    git(primary, "config", "user.name", "Test User")
    (primary / "README.md").write_text("# sample\n", encoding="utf-8")
    git(primary, "add", "README.md")
    git(primary, "commit", "-m", "init")
    active.parent.mkdir(parents=True)
    git(primary, "worktree", "add", "--detach", str(active), "HEAD")
    plan = active / ".ralph" / "plans" / "context-plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "# Context Plan\n\nImplementation notes required: yes\nImplementation notes status: active\nPlan approval status: approved\n\n## Purpose\nRecover implementation choices without reading full notes.\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["CODEX_SESSION_ID"] = "context-session"
    env["RALPH_HOME"] = str(tmp_path / "ralph")
    env["CODEX_MEMORY_HOME"] = str(tmp_path / "memory")
    env["RALPH_LOCAL_NOTES_ROOTS"] = ""
    created = run(
        [sys.executable, str(CREATE), "--plan", str(plan), "--active-root", str(active), "--primary-root", str(primary)],
        ROOT,
        env,
    )
    assert created.returncode == 0, created.stderr
    notes = primary / ".ralph" / "plans" / "context-plan-implementation-notes.html"
    append_note(
        active=active,
        primary=primary,
        env=env,
        notes=notes,
        category="decision",
        decision="Keep automatic retrieval bounded and deterministic.",
        reason="Ambiguous context can mislead recovery.",
        impact="Only one matching active plan can be selected automatically.",
    )
    return primary, active, plan, env


def append_note(
    *,
    active: Path,
    primary: Path,
    env: dict[str, str],
    notes: Path,
    category: str,
    decision: str,
    reason: str,
    impact: str,
) -> None:
    appended = run(
        [
            sys.executable,
            str(APPEND),
            "--notes",
            str(notes),
            "--category",
            category,
            "--decision",
            decision,
            "--reason",
            reason,
            "--impact",
            impact,
            "--active-root",
            str(active),
            "--primary-root",
            str(primary),
        ],
        ROOT,
        env,
    )
    assert appended.returncode == 0, appended.stderr


def test_implementation_context_selection_and_reader_are_bounded(tmp_path: Path) -> None:
    primary, active, plan, env = fixture_repo(tmp_path)
    canonical = primary / ".ralph" / "plans" / plan.name

    from_state = select_implementation_context(active_root=active, primary_root=primary, session_id="context-session", explicit_plan=None)
    from_index = select_implementation_context(active_root=active, primary_root=primary, session_id="fresh-session", explicit_plan=None)
    assert from_state and from_state.selection_reason == "session_state"
    assert from_index and from_index.selection_reason == "active_index"
    assert from_index.plan_path == canonical

    reader = run(
        [
            sys.executable,
            str(READER),
            "--active-root",
            str(active),
            "--primary-root",
            str(primary),
            "--session-id",
            "fresh-session",
            "--format",
            "json",
        ],
        ROOT,
        env,
    )
    assert reader.returncode == 0, reader.stderr
    payload = json.loads(reader.stdout)
    assert payload["selection"]["selection_reason"] == "active_index"
    assert len(payload["text"]) <= 2_000
    assert "<!doctype html>" not in reader.stdout
    assert "## Active Implementation Context" in payload["text"]


def test_continuation_injects_changed_notes_once_per_session(tmp_path: Path) -> None:
    _primary, active, _plan, env = fixture_repo(tmp_path)
    hook_payload = json.dumps(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "context-session",
            "cwd": str(active),
            "prompt": "continue",
        }
    )
    first = subprocess.run(
        [sys.executable, str(CONTINUITY)],
        cwd=ROOT,
        env=env,
        input=hook_payload,
        text=True,
        capture_output=True,
        check=False,
    )
    second = subprocess.run(
        [sys.executable, str(CONTINUITY)],
        cwd=ROOT,
        env=env,
        input=hook_payload,
        text=True,
        capture_output=True,
        check=False,
    )
    assert first.returncode == second.returncode == 0
    assert "## Active Implementation Context" in first.stdout
    assert second.stdout == ""
    [trace] = list((Path(env["RALPH_HOME"]) / "projects").glob("*/traces/implementation-context.jsonl"))
    record = json.loads(trace.read_text(encoding="utf-8").splitlines()[-1])
    assert record["selection_reason"] == "session_state"
    assert "text" not in record
    assert record["selected_entry_hashes"]


def test_wakeup_injects_active_implementation_context_once(tmp_path: Path) -> None:
    _primary, active, _plan, env = fixture_repo(tmp_path)
    command = [
        sys.executable,
        str(WAKEUP),
        "--project",
        "sample-project",
        "--project-id",
        "project-id",
        "--workspace-root",
        str(active),
        "--implementation-context",
    ]
    first = run(command, ROOT, env)
    second = run(command, ROOT, env)
    assert first.returncode == second.returncode == 0
    assert "## Active Implementation Context" in first.stdout
    assert "## Active Implementation Context" not in second.stdout


def test_wakeup_keeps_legacy_implementation_context_off_without_explicit_flag(tmp_path: Path) -> None:
    _primary, active, _plan, env = fixture_repo(tmp_path)
    command = [
        sys.executable,
        str(WAKEUP),
        "--project",
        "sample-project",
        "--project-id",
        "project-id",
        "--workspace-root",
        str(active),
    ]
    result = run(command, ROOT, env)
    assert result.returncode == 0, result.stderr
    assert "## Active Implementation Context" not in result.stdout


def test_automatic_recovery_matches_explicit_lookup_without_wrong_plan_selection(tmp_path: Path) -> None:
    primary, active, plan, env = fixture_repo(tmp_path)
    notes = primary / ".ralph" / "plans" / "context-plan-implementation-notes.html"
    recovery_entries = [
        ("deviation", "Keep recovery injection limited to lifecycle entry points."),
        ("open-question", "Global activation remains pending explicit approval."),
        ("validation", "Bounded recovery fixture passed with no raw note body persisted."),
    ]
    for category, decision in recovery_entries:
        append_note(
            active=active,
            primary=primary,
            env=env,
            notes=notes,
            category=category,
            decision=decision,
            reason="Recovery must preserve material state without broad context injection.",
            impact="A fresh agent can continue from the active plan context.",
        )

    explicit = run(
        [
            sys.executable,
            str(READER),
            "--active-root",
            str(active),
            "--primary-root",
            str(primary),
            "--session-id",
            "explicit-recovery",
            "--plan",
            str(plan),
            "--format",
            "json",
        ],
        ROOT,
        env,
    )
    automatic = run(
        [
            sys.executable,
            str(READER),
            "--active-root",
            str(active),
            "--primary-root",
            str(primary),
            "--session-id",
            "fresh-recovery",
            "--format",
            "json",
        ],
        ROOT,
        env,
    )
    assert explicit.returncode == automatic.returncode == 0
    explicit_payload = json.loads(explicit.stdout)
    automatic_payload = json.loads(automatic.stdout)
    assert explicit_payload["selection"]["selection_reason"] == "explicit"
    assert automatic_payload["selection"]["selection_reason"] == "active_index"
    expected_facts = [
        "Recover implementation choices without reading full notes.",
        "Keep automatic retrieval bounded and deterministic.",
        "Keep recovery injection limited to lifecycle entry points.",
        "Global activation remains pending explicit approval.",
        "Bounded recovery fixture passed with no raw note body persisted.",
    ]
    for fact in expected_facts:
        assert fact in explicit_payload["text"]
        assert fact in automatic_payload["text"]
    assert len(automatic_payload["text"].split()) <= 250
    assert len(automatic_payload["text"]) <= 2_000
    assert len(automatic_payload["text"]) / 4 <= 500

    unrelated_plan = active / ".ralph" / "plans" / "unrelated-plan.md"
    unrelated_plan.write_text(
        "# Unrelated Plan\n\nImplementation notes required: yes\nImplementation notes status: active\nPlan approval status: approved\n",
        encoding="utf-8",
    )
    created = run(
        [sys.executable, str(CREATE), "--plan", str(unrelated_plan), "--active-root", str(active), "--primary-root", str(primary)],
        ROOT,
        env,
    )
    assert created.returncode == 0, created.stderr
    ambiguous = run(
        [
            sys.executable,
            str(READER),
            "--active-root",
            str(active),
            "--primary-root",
            str(primary),
            "--session-id",
            "ambiguous-recovery",
            "--format",
            "json",
        ],
        ROOT,
        env,
    )
    assert ambiguous.returncode == 0, ambiguous.stderr
    assert json.loads(ambiguous.stdout) == {"selection": None, "text": ""}
