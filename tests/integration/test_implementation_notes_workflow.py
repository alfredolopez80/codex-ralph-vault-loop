from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CREATE = ROOT / "scripts" / "plans" / "create-implementation-notes.py"
APPEND = ROOT / "scripts" / "plans" / "append-implementation-note.py"
HOOK = ROOT / ".codex" / "hooks" / "implementation_notes_guard.py"


def run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None, input_text: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, input=input_text, text=True, capture_output=True, check=False)


def git(cwd: Path, *args: str) -> None:
    result = run(["git", *args], cwd=cwd)
    assert result.returncode == 0, result.stderr


def make_repo_with_worktree(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    home = tmp_path / "home"
    primary = tmp_path / "primary" / "codex-ralph-vault-loop"
    active = home / ".codex" / "worktrees" / "fixture" / "codex-ralph-vault-loop"
    primary.mkdir(parents=True)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["RALPH_PRIMARY_REPO_ROOT"] = str(primary)
    git(primary, "init")
    git(primary, "config", "user.email", "test@example.invalid")
    git(primary, "config", "user.name", "Test User")
    (primary / "README.md").write_text("# fixture\n", encoding="utf-8")
    git(primary, "add", "README.md")
    git(primary, "commit", "-m", "init")
    active.parent.mkdir(parents=True)
    git(primary, "worktree", "add", "--detach", str(active), "HEAD")
    return primary, active, env


def write_plan(path: Path, *, approved: bool = True, notes: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    status = "approved" if approved else "pending"
    note_line = f"Implementation notes: {notes}\n" if notes else ""
    path.write_text(
        "# Fixture Plan\n\n"
        f"{note_line}"
        "Implementation notes required: yes\n"
        "Implementation notes status: pending\n"
        f"Plan approval status: {status}\n",
        encoding="utf-8",
    )


def hook_payload(plan: Path, cwd: Path, *, approved: bool = False) -> str:
    return json.dumps(
        {
            "hook_event_name": "Stop",
            "session_id": "fixture-session",
            "cwd": str(cwd),
            "implementation_plan_path": str(plan),
            "plan_approved": approved,
            "last_assistant_message": "Implementation completed with notes.",
        }
    )


def stop_payload_without_plan(cwd: Path, session_id: str) -> str:
    return json.dumps(
        {
            "hook_event_name": "Stop",
            "session_id": session_id,
            "cwd": str(cwd),
            "last_assistant_message": "Implementation completed with notes.",
        }
    )


def test_implementation_notes_workflow_survives_worktree_cleanup(tmp_path: Path) -> None:
    primary, active, env = make_repo_with_worktree(tmp_path)
    source_plan = active / ".ralph" / "plans" / "2026-05-19-fixture-plan.md"
    write_plan(source_plan)

    created = run(
        [
            sys.executable,
            str(CREATE),
            "--plan",
            str(source_plan),
            "--active-root",
            str(active),
            "--primary-root",
            str(primary),
        ],
        cwd=ROOT,
        env=env,
    )
    assert created.returncode == 0, created.stderr
    canonical_plan = primary / ".ralph" / "plans" / source_plan.name
    notes = primary / ".ralph" / "plans" / "2026-05-19-fixture-plan-implementation-notes.html"
    assert canonical_plan.is_file()
    assert notes.is_file()

    appended = run(
        [
            sys.executable,
            str(APPEND),
            "--notes",
            str(notes),
            "--category",
            "decision",
            "--decision",
            "Use canonical repo-root notes for durable traceability.",
            "--reason",
            "The active worktree is disposable.",
            "--impact",
            "Finalization checks the primary repo copy.",
            "--related-file",
            "scripts/plans/create-implementation-notes.py",
            "--primary-root",
            str(primary),
            "--active-root",
            str(active),
        ],
        cwd=ROOT,
        env=env,
    )
    assert appended.returncode == 0, appended.stderr
    appended_validation = run(
        [
            sys.executable,
            str(APPEND),
            "--notes",
            str(notes),
            "--category",
            "validation",
            "--decision",
            "Validated canonical notes grouping.",
            "--reason",
            "The notes file should be readable by category.",
            "--impact",
            "Validation entries stay under the validation section.",
            "--primary-root",
            str(primary),
            "--active-root",
            str(active),
        ],
        cwd=ROOT,
        env=env,
    )
    assert appended_validation.returncode == 0, appended_validation.stderr
    html = notes.read_text(encoding="utf-8")
    assert str(primary) in html
    assert str(active) in html
    assert 'data-entry-kind="decision"' in html
    assert 'data-entry-section="decision"' in html
    assert 'data-entry-section="validation"' in html
    assert ".entry-section:not(:has(.entry))" in html
    decision_anchor = "<!-- IMPLEMENTATION_NOTES_DECISION_ANCHOR -->"
    validation_anchor = "<!-- IMPLEMENTATION_NOTES_VALIDATION_ANCHOR -->"
    assert html.index('data-entry-section="decision"') < html.index("Use canonical repo-root notes") < html.index(decision_anchor)
    assert html.index('data-entry-section="validation"') < html.index("Validated canonical notes grouping") < html.index(validation_anchor)
    assert "<script" not in html
    assert "http://" not in html
    assert "https://" not in html

    guarded = run([sys.executable, str(HOOK)], cwd=ROOT, env=env, input_text=hook_payload(canonical_plan, active))
    assert guarded.returncode == 0, guarded.stderr
    assert guarded.stdout == ""

    if (active / ".ralph").exists():
        shutil.rmtree(active / ".ralph")
    assert notes.is_file()


def test_stop_guard_uses_session_state_when_final_message_omits_plan_path(tmp_path: Path) -> None:
    primary, active, env = make_repo_with_worktree(tmp_path)
    env["CODEX_SESSION_ID"] = "session-with-plan-state"
    source_plan = active / ".ralph" / "plans" / "2026-05-19-session-plan.md"
    write_plan(source_plan)

    created = run(
        [
            sys.executable,
            str(CREATE),
            "--plan",
            str(source_plan),
            "--active-root",
            str(active),
            "--primary-root",
            str(primary),
        ],
        cwd=ROOT,
        env=env,
    )
    assert created.returncode == 0, created.stderr
    notes = primary / ".ralph" / "plans" / "2026-05-19-session-plan-implementation-notes.html"
    notes.unlink()

    guarded = run([sys.executable, str(HOOK)], cwd=ROOT, env=env, input_text=stop_payload_without_plan(active, "session-with-plan-state"))
    assert guarded.returncode == 0, guarded.stderr
    data = json.loads(guarded.stdout)
    assert data["decision"] == "block"
    assert "notes file was not found" in data["reason"]


def test_guard_blocks_when_notes_exist_without_approved_plan(tmp_path: Path) -> None:
    primary, active, env = make_repo_with_worktree(tmp_path)
    plan = primary / ".ralph" / "plans" / "pending-plan.md"
    write_plan(plan, approved=False)
    notes = primary / ".ralph" / "plans" / "pending-plan-implementation-notes.html"
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text('<main data-implementation-notes="true"><article data-entry-kind="decision"></article></main>', encoding="utf-8")

    guarded = run([sys.executable, str(HOOK)], cwd=ROOT, env=env, input_text=hook_payload(plan, active))
    assert guarded.returncode == 0, guarded.stderr
    data = json.loads(guarded.stdout)
    assert data["decision"] == "block"
    assert "not approved" in data["reason"]


def test_guard_blocks_when_required_notes_are_missing(tmp_path: Path) -> None:
    primary, active, env = make_repo_with_worktree(tmp_path)
    plan = primary / ".ralph" / "plans" / "approved-plan.md"
    write_plan(plan, approved=True)

    guarded = run([sys.executable, str(HOOK)], cwd=ROOT, env=env, input_text=hook_payload(plan, active))
    assert guarded.returncode == 0, guarded.stderr
    data = json.loads(guarded.stdout)
    assert data["decision"] == "block"
    assert "notes file was not found" in data["reason"]


def test_guard_rejects_marker_only_notes(tmp_path: Path) -> None:
    primary, active, env = make_repo_with_worktree(tmp_path)
    plan = primary / ".ralph" / "plans" / "approved-plan.md"
    write_plan(plan, approved=True)
    notes = primary / ".ralph" / "plans" / "approved-plan-implementation-notes.html"
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text('<main data-implementation-notes="true"><article data-entry-kind="decision"></article></main>', encoding="utf-8")

    guarded = run([sys.executable, str(HOOK)], cwd=ROOT, env=env, input_text=hook_payload(plan, active))
    assert guarded.returncode == 0, guarded.stderr
    data = json.loads(guarded.stdout)
    assert data["decision"] == "block"
    assert "restrictive CSP" in data["reason"] or "required fields" in data["reason"]


def test_plan_metadata_prefers_top_level_values_over_later_examples(tmp_path: Path) -> None:
    primary, active, env = make_repo_with_worktree(tmp_path)
    plan = primary / ".ralph" / "plans" / "approved-plan.md"
    notes = primary / ".ralph" / "plans" / "approved-plan-implementation-notes.html"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(
        "# Approved Plan\n\n"
        f"Implementation notes: {notes}\n"
        "Implementation notes required: yes\n"
        "Implementation notes status: complete\n"
        "Plan approval status: approved\n\n"
        "## Example Metadata\n\n"
        "Implementation notes: <primary-repo-root>/.ralph/plans/YYYY-MM-DD-<slug>-implementation-notes.html\n"
        "Implementation notes required: yes\n"
        "Implementation notes status: pending|active|complete\n"
        "Plan approval status: pending|approved\n",
        encoding="utf-8",
    )
    created = run([sys.executable, str(CREATE), "--plan", str(plan), "--active-root", str(active), "--primary-root", str(primary)], cwd=ROOT, env=env)
    assert created.returncode == 0, created.stderr
    appended = run(
        [
            sys.executable,
            str(APPEND),
            "--notes",
            str(notes),
            "--category",
            "decision",
            "--decision",
            "Validate metadata precedence with a real note.",
            "--reason",
            "The guard should not accept fake marker-only HTML.",
            "--impact",
            "Metadata parsing is tested with generated notes.",
            "--primary-root",
            str(primary),
            "--active-root",
            str(active),
        ],
        cwd=ROOT,
        env=env,
    )
    assert appended.returncode == 0, appended.stderr

    guarded = run([sys.executable, str(HOOK)], cwd=ROOT, env=env, input_text=hook_payload(plan, active))
    assert guarded.returncode == 0, guarded.stderr
    assert guarded.stdout == ""


def test_metadata_examples_inside_code_fences_do_not_override_real_values(tmp_path: Path) -> None:
    primary, active, env = make_repo_with_worktree(tmp_path)
    plan = primary / ".ralph" / "plans" / "approved-plan.md"
    notes = primary / ".ralph" / "plans" / "approved-plan-implementation-notes.html"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(
        "# Approved Plan\n\n"
        "```markdown\n"
        "Implementation notes: <primary-repo-root>/.ralph/plans/example.html\n"
        "Implementation notes required: no\n"
        "Plan approval status: pending\n"
        "```\n\n"
        f"Implementation notes: {notes}\n"
        "Implementation notes required: yes\n"
        "Implementation notes status: complete\n"
        "Plan approval status: approved\n",
        encoding="utf-8",
    )
    created = run([sys.executable, str(CREATE), "--plan", str(plan), "--active-root", str(active), "--primary-root", str(primary)], cwd=ROOT, env=env)
    assert created.returncode == 0, created.stderr
    appended = run(
        [
            sys.executable,
            str(APPEND),
            "--notes",
            str(notes),
            "--category",
            "decision",
            "--decision",
            "Validate fenced metadata examples.",
            "--reason",
            "Examples should not become plan metadata.",
            "--impact",
            "Real metadata remains authoritative.",
            "--primary-root",
            str(primary),
            "--active-root",
            str(active),
        ],
        cwd=ROOT,
        env=env,
    )
    assert appended.returncode == 0, appended.stderr

    guarded = run([sys.executable, str(HOOK)], cwd=ROOT, env=env, input_text=hook_payload(plan, active))
    assert guarded.returncode == 0, guarded.stderr
    assert guarded.stdout == ""


def test_create_canonicalizes_worktree_metadata_notes_path(tmp_path: Path) -> None:
    primary, active, env = make_repo_with_worktree(tmp_path)
    worktree_notes = active / ".ralph" / "plans" / "worktree-plan-implementation-notes.html"
    source_plan = active / ".ralph" / "plans" / "worktree-plan.md"
    write_plan(source_plan, notes=str(worktree_notes))

    created = run(
        [
            sys.executable,
            str(CREATE),
            "--plan",
            str(source_plan),
            "--active-root",
            str(active),
            "--primary-root",
            str(primary),
        ],
        cwd=ROOT,
        env=env,
    )
    assert created.returncode == 0, created.stderr
    canonical_plan = primary / ".ralph" / "plans" / "worktree-plan.md"
    notes = primary / ".ralph" / "plans" / "worktree-plan-implementation-notes.html"
    assert f"Implementation notes: {notes}" in canonical_plan.read_text(encoding="utf-8")
    appended = run(
        [
            sys.executable,
            str(APPEND),
            "--notes",
            str(notes),
            "--category",
            "decision",
            "--decision",
            "Use canonical notes despite worktree metadata.",
            "--reason",
            "Worktree-local notes are disposable.",
            "--impact",
            "Cleanup does not delete the durable copy.",
            "--primary-root",
            str(primary),
            "--active-root",
            str(active),
        ],
        cwd=ROOT,
        env=env,
    )
    assert appended.returncode == 0, appended.stderr
    shutil.rmtree(active / ".ralph")

    guarded = run([sys.executable, str(HOOK)], cwd=ROOT, env=env, input_text=hook_payload(canonical_plan, active))
    assert guarded.returncode == 0, guarded.stderr
    assert guarded.stdout == ""


def test_append_migrates_legacy_loose_entries_into_category_sections(tmp_path: Path) -> None:
    primary, active, env = make_repo_with_worktree(tmp_path)
    notes = primary / ".ralph" / "plans" / "legacy-implementation-notes.html"
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text(
        "<style>\n"
        "    h2 { margin-top: 32px; padding-bottom: 6px; border-bottom: 1px solid #d1d5db; }\n"
        "</style>\n"
        '<main data-implementation-notes="true">\n'
        '    <section aria-labelledby="decisions-heading"><h2 id="decisions-heading">Design Decisions</h2></section>\n'
        '    <section aria-labelledby="deviations-heading"><h2 id="deviations-heading">Deviations From Spec</h2></section>\n'
        '    <section aria-labelledby="tradeoffs-heading"><h2 id="tradeoffs-heading">Tradeoffs Considered</h2></section>\n'
        '    <section aria-labelledby="questions-heading"><h2 id="questions-heading">Open Questions</h2></section>\n'
        '    <section aria-labelledby="validation-heading"><h2 id="validation-heading">Validation Notes</h2></section>\n'
        '    <section aria-labelledby="final-heading"><h2 id="final-heading">Final Implementation Summary</h2></section>\n'
        '\n'
        '    <article class="entry" data-entry-kind="decision">\n'
        '      <h3>Design Decisions</h3>\n'
        "      <dl><dt>Decision</dt><dd>Legacy decision</dd></dl>\n"
        "    </article>\n"
        '\n'
        '    <article class="entry" data-entry-kind="validation">\n'
        '      <h3>Validation Notes</h3>\n'
        "      <dl><dt>Decision</dt><dd>Legacy validation</dd></dl>\n"
        "    </article>\n"
        "    <!-- IMPLEMENTATION_NOTES_APPEND_ANCHOR -->\n"
        "</main>\n",
        encoding="utf-8",
    )

    appended = run(
        [
            sys.executable,
            str(APPEND),
            "--notes",
            str(notes),
            "--category",
            "decision",
            "--decision",
            "New grouped decision",
            "--primary-root",
            str(primary),
            "--active-root",
            str(active),
        ],
        cwd=ROOT,
        env=env,
    )
    assert appended.returncode == 0, appended.stderr
    html = notes.read_text(encoding="utf-8")
    assert html.index('data-entry-section="decision"') < html.index("Legacy decision") < html.index("New grouped decision")
    assert html.index("New grouped decision") < html.index("IMPLEMENTATION_NOTES_DECISION_ANCHOR")
    assert html.index('data-entry-section="validation"') < html.index("Legacy validation")
    assert html.index("Legacy validation") < html.index("IMPLEMENTATION_NOTES_VALIDATION_ANCHOR")
    assert ".entry-section:not(:has(.entry))" in html
    assert "<h3>Design Decisions</h3>" not in html
    assert "<h3>Validation Notes</h3>" not in html


def test_red_content_and_path_escape_are_rejected(tmp_path: Path) -> None:
    primary, active, env = make_repo_with_worktree(tmp_path)
    plan = active / ".ralph" / "plans" / "safe-plan.md"
    write_plan(plan)

    traversal = run(
        [
            sys.executable,
            str(CREATE),
            "--plan",
            str(plan),
            "--notes",
            str(primary / ".ralph" / "plans" / ".." / "escape.html"),
            "--active-root",
            str(active),
            "--primary-root",
            str(primary),
        ],
        cwd=ROOT,
        env=env,
    )
    assert traversal.returncode != 0
    assert "path traversal" in traversal.stderr
    assert not (primary / ".ralph" / "plans" / "safe-plan.md").exists()

    sensitive_filename = run(
        [
            sys.executable,
            str(CREATE),
            "--plan",
            str(plan),
            "--notes",
            str(primary / ".ralph" / "plans" / "token-output.html"),
            "--active-root",
            str(active),
            "--primary-root",
            str(primary),
        ],
        cwd=ROOT,
        env=env,
    )
    assert sensitive_filename.returncode != 0
    assert "sensitive filename" in sensitive_filename.stderr

    create_ok = run(
        [sys.executable, str(CREATE), "--plan", str(plan), "--active-root", str(active), "--primary-root", str(primary)],
        cwd=ROOT,
        env=env,
    )
    assert create_ok.returncode == 0, create_ok.stderr
    notes = primary / ".ralph" / "plans" / "safe-plan-implementation-notes.html"
    red = run(
        [
            sys.executable,
            str(APPEND),
            "--notes",
            str(notes),
            "--category",
            "decision",
            "--decision",
            "token=abc123",
            "--primary-root",
            str(primary),
            "--active-root",
            str(active),
        ],
        cwd=ROOT,
        env=env,
    )
    assert red.returncode != 0
    assert "RED-sensitive" in red.stderr
    assert "token=abc123" not in notes.read_text(encoding="utf-8")

    injection = run(
        [
            sys.executable,
            str(APPEND),
            "--notes",
            str(notes),
            "--category",
            "decision",
            "--decision",
            "\"><img src=x onerror=alert(1)>",
            "--reason",
            "<script>alert(1)</script>",
            "--impact",
            "javascript:alert(1)",
            "--related-file",
            "docs/implementation-notes.md",
            "--primary-root",
            str(primary),
            "--active-root",
            str(active),
        ],
        cwd=ROOT,
        env=env,
    )
    assert injection.returncode == 0, injection.stderr
    html = notes.read_text(encoding="utf-8")
    assert "<script" not in html
    assert "<img" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_symlink_escape_and_worktree_only_notes_are_rejected(tmp_path: Path) -> None:
    primary, active, env = make_repo_with_worktree(tmp_path)
    plan = active / ".ralph" / "plans" / "safe-plan.md"
    write_plan(plan)

    outside = tmp_path / "outside.html"
    link = primary / ".ralph" / "plans" / "linked.html"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside)
    symlink = run(
        [
            sys.executable,
            str(CREATE),
            "--plan",
            str(plan),
            "--notes",
            str(link),
            "--active-root",
            str(active),
            "--primary-root",
            str(primary),
            "--force",
        ],
        cwd=ROOT,
        env=env,
    )
    assert symlink.returncode != 0
    assert "escapes allowed" in symlink.stderr

    sensitive_target = primary / ".ralph" / "plans" / "token-output.html"
    sensitive_link = primary / ".ralph" / "plans" / "public-notes.html"
    sensitive_link.symlink_to(sensitive_target)
    sensitive_symlink = run(
        [
            sys.executable,
            str(CREATE),
            "--plan",
            str(plan),
            "--notes",
            str(sensitive_link),
            "--active-root",
            str(active),
            "--primary-root",
            str(primary),
            "--force",
        ],
        cwd=ROOT,
        env=env,
    )
    assert sensitive_symlink.returncode != 0
    assert "sensitive filename" in sensitive_symlink.stderr

    worktree_only = run(
        [
            sys.executable,
            str(CREATE),
            "--plan",
            str(plan),
            "--notes",
            str(active / ".ralph" / "plans" / "worktree-only.html"),
            "--active-root",
            str(active),
            "--primary-root",
            str(primary),
        ],
        cwd=ROOT,
        env=env,
    )
    assert worktree_only.returncode != 0
    assert "escapes allowed" in worktree_only.stderr

    worktree_append_notes = active / ".ralph" / "plans" / "worktree-only.html"
    worktree_append_notes.parent.mkdir(parents=True, exist_ok=True)
    worktree_append_notes.write_text("<main data-implementation-notes=\"true\"></main>", encoding="utf-8")
    worktree_append = run(
        [
            sys.executable,
            str(APPEND),
            "--notes",
            str(worktree_append_notes),
            "--category",
            "decision",
            "--decision",
            "Should not append to worktree-only notes.",
            "--active-root",
            str(active),
            "--primary-root",
            str(active),
        ],
        cwd=ROOT,
        env=env,
    )
    assert worktree_append.returncode != 0
    assert "primary repo root cannot be under" in worktree_append.stderr
