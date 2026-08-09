from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "plans" / "progress.py"
CREATE = ROOT / "scripts" / "plans" / "create-implementation-notes.py"


def run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=cwd,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        check=False,
    )


def git(cwd: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def repo(tmp_path: Path, *, plan_name: str = "demo") -> tuple[Path, Path]:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "CLI Test")
    (root / "README.md").write_text("# fixture\n", encoding="utf-8")
    git(root, "add", "README.md")
    git(root, "commit", "-qm", "fixture")
    plan = root / ".ralph" / "plans" / f"{plan_name}.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Fixture Plan\n", encoding="utf-8")
    return root, plan


def json_result(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert result.stdout, result.stderr
    return json.loads(result.stdout)


def start(root: Path, plan: Path, operation: str = "start-1") -> dict[str, object]:
    result = run_cli(
        root,
        "start",
        "--plan",
        str(plan),
        "--operation-id",
        operation,
        "--format",
        "json",
    )
    assert result.returncode == 0, result.stderr
    return json_result(result)


def test_every_public_command_and_output_contract(tmp_path: Path) -> None:
    root, plan = repo(tmp_path)
    started = start(root, plan)
    assert started["command"] == "start"
    assert started["changed"] is True
    assert started["source_digest"].startswith("sha256:")

    recorded = run_cli(
        root,
        "record",
        "--plan",
        str(plan),
        "--kind",
        "decision",
        "--summary",
        "Use one bounded public CLI",
        "--operation-id",
        "decision-1",
        "--json",
    )
    assert recorded.returncode == 0, recorded.stderr
    assert json_result(recorded)["changed"] is True

    phase = run_cli(
        root,
        "phase",
        "--plan",
        str(plan),
        "--phase",
        "validation",
        "--next",
        "Run focused tests",
        "--format",
        "json",
    )
    assert phase.returncode == 0, phase.stderr
    assert json_result(phase)["event_id"]

    validation = run_cli(
        root,
        "validate",
        "--plan",
        str(plan),
        "--gate",
        "unit",
        "--result",
        "pass",
        "--format",
        "json",
    )
    assert validation.returncode == 0, validation.stderr

    status_json = run_cli(root, "status", "--plan", str(plan), "--format", "json")
    assert status_json.returncode == 0, status_json.stderr
    status = json_result(status_json)
    assert status["state"]["phase"] == "validation"
    assert status["state"]["validation"] == {"unit": "pass"}
    status_text = run_cli(root, "status", "--plan", str(plan), "--format", "text")
    assert status_text.returncode == 0
    assert "Status:" in status_text.stdout and "Source digest:" in status_text.stdout

    for profile, limit in (("luna", 512), ("terra", 192), ("sol", 96), ("unknown", 96)):
        context = run_cli(root, "context", "--plan", str(plan), "--profile", profile, "--format", "json")
        assert context.returncode == 0, context.stderr
        capsule = json_result(context)
        assert capsule["budget_bytes"] == limit
        assert len(str(capsule["capsule"]).encode("utf-8")) <= limit

    for export_format in ("markdown", "html", "legacy-index", "consolidated"):
        exported = run_cli(root, "export", "--plan", str(plan), "--format", export_format, "--json")
        assert exported.returncode == 0, exported.stderr
        payload = json_result(exported)
        assert payload["persisted"] is False
        assert payload["source_digest"].startswith("sha256:")
        assert payload["output_digest"].startswith("sha256:")
        assert payload["content"]

    output = root / "derived" / "progress.md"
    persisted = run_cli(
        root,
        "export",
        "--plan",
        str(plan),
        "--format",
        "markdown",
        "--output",
        str(output),
        "--json",
    )
    assert persisted.returncode == 0, persisted.stderr
    persisted_payload = json_result(persisted)
    assert persisted_payload["persisted"] is True
    assert output.is_file()
    applied_export = run_cli(
        root,
        "export",
        "--plan",
        str(plan),
        "--format",
        "consolidated",
        "--apply",
        "--json",
    )
    assert applied_export.returncode == 0, applied_export.stderr
    applied_payload = json_result(applied_export)
    assert applied_payload["persisted"] is True
    assert Path(str(applied_payload["output"])).is_file()

    verify = run_cli(root, "verify", "--plan", str(plan), "--format", "json")
    assert verify.returncode == 0, verify.stderr
    assert json_result(verify)["event_count"] == 4

    dry_run = run_cli(root, "migrate-legacy", "--dry-run", "--format", "json")
    assert dry_run.returncode == 0, dry_run.stderr
    assert json_result(dry_run)["command"] == "migrate-legacy"

    rebuilt = run_cli(root, "rebuild-legacy", "--plan", str(plan), "--format", "json")
    assert rebuilt.returncode == 0, rebuilt.stderr
    assert (root / ".ralph" / "plans" / "demo-implementation-notes.html").is_file()
    assert (root / ".ralph" / "plans" / "implementation-index.json").is_file()


def test_retry_conflict_and_red_input_have_stable_errors(tmp_path: Path) -> None:
    root, plan = repo(tmp_path)
    start(root, plan)
    first = run_cli(
        root,
        "record",
        "--plan",
        str(plan),
        "--kind",
        "decision",
        "--summary",
        "same payload",
        "--operation-id",
        "retry-1",
        "--json",
    )
    assert first.returncode == 0
    retry = run_cli(
        root,
        "record",
        "--plan",
        str(plan),
        "--kind",
        "decision",
        "--summary",
        "same payload",
        "--operation-id",
        "retry-1",
        "--json",
    )
    assert retry.returncode == 0
    assert json_result(retry)["changed"] is False

    conflict = run_cli(
        root,
        "record",
        "--plan",
        str(plan),
        "--kind",
        "decision",
        "--summary",
        "different payload",
        "--operation-id",
        "retry-1",
        "--json",
    )
    assert conflict.returncode == 4
    assert json_result(conflict)["error"] == {
        "code": "idempotency_conflict",
        "message": "operation ID conflicts with an existing payload",
    }

    red = run_cli(
        root,
        "record",
        "--plan",
        str(plan),
        "--kind",
        "decision",
        "--summary",
        "pass" + "word" + "=fixture-marker",
        "--json",
    )
    assert red.returncode == 3
    red_payload = json_result(red)
    assert red_payload["error"]["code"] == "red_content"
    assert "fixture-marker" not in red.stdout


def test_export_rejects_output_outside_canonical_checkout(tmp_path: Path) -> None:
    root, plan = repo(tmp_path)
    start(root, plan)
    outside = tmp_path / "outside.md"
    result = run_cli(
        root,
        "export",
        "--plan",
        str(plan),
        "--format",
        "markdown",
        "--output",
        str(outside),
        "--json",
    )
    assert result.returncode == 8
    assert json_result(result)["error"]["code"] == "export_output"
    assert not outside.exists()


def test_legacy_create_wrapper_has_explicit_compatibility_surface(tmp_path: Path) -> None:
    root, plan = repo(tmp_path)
    plan.write_text(
        "# Fixture Plan\n\n"
        "Implementation notes required: yes\n"
        "Plan approval status: approved\n",
        encoding="utf-8",
    )
    created = subprocess.run(
        [
            sys.executable,
            str(CREATE),
            "--compat-legacy",
            "--plan",
            str(plan),
            "--active-root",
            str(root),
            "--primary-root",
            str(root),
            "--force",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert created.returncode == 0, created.stderr
    assert "IMPLEMENTATION_NOTES_CREATED" in created.stdout
    assert (root / ".ralph" / "plans" / "demo-implementation-notes.html").is_file()


def test_apply_migration_is_explicit_and_machine_readable(tmp_path: Path) -> None:
    root, plan = repo(tmp_path)
    dry_run = run_cli(root, "migrate-legacy", "--dry-run", "--format", "json")
    assert dry_run.returncode == 0, dry_run.stderr
    assert json_result(dry_run)["file_count"] == 1
    assert not (root / ".local-notes").exists()

    # Apply is explicit even when the only legacy source is a plan document.
    applied = run_cli(root, "migrate-legacy", "--apply", "--format", "json")
    assert applied.returncode == 0, applied.stderr
    payload = json_result(applied)
    assert payload["mode"] == "apply"
    assert payload["imported_plans"] == 1
    assert (root / ".local-notes" / "ralph" / "implementation").exists()


def test_apply_migration_imports_legacy_notes_without_deleting_sources(tmp_path: Path) -> None:
    root, plan = repo(tmp_path)
    plan.write_text(
        "# Fixture Plan\n\n"
        "Implementation notes required: yes\n"
        "Plan approval status: approved\n",
        encoding="utf-8",
    )
    created = subprocess.run(
        [
            sys.executable,
            str(CREATE),
            "--compat-legacy",
            "--plan",
            str(plan),
            "--active-root",
            str(root),
            "--primary-root",
            str(root),
            "--force",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert created.returncode == 0, created.stderr
    notes = root / ".ralph" / "plans" / "demo-implementation-notes.html"
    appended = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "plans" / "append-implementation-note.py"),
            "--compat-legacy",
            "--notes",
            str(notes),
            "--category",
            "decision",
            "--decision",
            "Legacy evidence remains readable",
            "--reason",
            "The reader-first boundary preserves the source.",
            "--impact",
            "Migration can be retried safely.",
            "--primary-root",
            str(root),
            "--active-root",
            str(root),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert appended.returncode == 0, appended.stderr
    before = notes.read_bytes()
    applied = run_cli(root, "migrate-legacy", "--apply", "--format", "json")
    assert applied.returncode == 0, applied.stderr
    payload = json_result(applied)
    assert payload["imported_plans"] == 1
    assert payload["imported_events"] >= 1
    assert notes.read_bytes() == before

    rebuilt = run_cli(root, "rebuild-legacy", "--plan", str(plan), "--format", "json")
    assert rebuilt.returncode == 0, rebuilt.stderr


@pytest.mark.parametrize("command", ["status", "verify", "context", "export"])
def test_unregistered_plan_is_typed_and_bounded(tmp_path: Path, command: str) -> None:
    root, plan = repo(tmp_path)
    args = [command, "--plan", str(plan), "--json"]
    if command == "context":
        args.extend(["--profile", "luna"])
    if command == "export":
        args.extend(["--format", "markdown"])
    result = run_cli(root, *args)
    assert result.returncode == 6
    payload = json_result(result)
    assert payload["error"]["code"] == "plan_not_registered"
    assert str(plan) not in result.stdout
