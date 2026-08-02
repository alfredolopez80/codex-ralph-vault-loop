from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = ROOT / "scripts" / "memory" / "user_memory.py"


def run_gateway(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["RALPH_HOME"] = str(home)
    return subprocess.run(
        [sys.executable, str(GATEWAY), *args], cwd=ROOT, env=env,
        text=True, capture_output=True, check=False,
    )


def receipt_id(output: str) -> str:
    return next(field.split("=", 1)[1] for field in output.split() if field.startswith("id="))


def test_yellow_global_is_explicit_and_idempotent(tmp_path: Path) -> None:
    args = ("remember", "--text", "private repo migration policy marker", "--scope", "global")
    first = run_gateway(tmp_path, *args)
    second = run_gateway(tmp_path, *args)

    assert first.returncode == second.returncode == 0
    assert "USER_MEMORY_OK_CREATED" in first.stdout
    assert "scope=global classification=YELLOW" in first.stdout
    assert "USER_MEMORY_OK_UNCHANGED" in second.stdout
    assert receipt_id(first.stdout) == receipt_id(second.stdout)
    records = list((tmp_path / "ledgers" / "user").glob("um-*.md"))
    assert len(records) == 1
    assert 'authoritative: "false"' in records[0].read_text()


def test_authority_upgrade_updates_existing_record(tmp_path: Path) -> None:
    created = run_gateway(tmp_path, "remember", "--text", "authority upgrade marker", "--scope", "global")
    memory_id = receipt_id(created.stdout)

    upgraded = run_gateway(
        tmp_path,
        "remember",
        "--text",
        "authority upgrade marker",
        "--scope",
        "global",
        "--authoritative",
    )

    record = (tmp_path / "ledgers" / "user" / f"{memory_id}.md").read_text()
    assert upgraded.returncode == 0
    assert "USER_MEMORY_OK_UPDATED" in upgraded.stdout
    assert "authoritative=true" in upgraded.stdout
    assert 'authoritative: "true"' in record


def test_invalid_workspace_root_is_rejected(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    result = run_gateway(
        tmp_path,
        "remember",
        "--text",
        "invalid workspace marker",
        "--scope",
        "global",
        "--workspace-root",
        str(missing),
    )

    assert result.returncode != 0
    assert result.stdout.strip() == "USER_MEMORY_REJECTED_INVALID_WORKSPACE_ROOT"
    assert not list(tmp_path.rglob("um-*.md"))


def test_scope_defaults_repo_and_authority_is_independent(tmp_path: Path) -> None:
    result = run_gateway(tmp_path, "remember", "--text", "repo memory scope marker", "--authoritative")

    assert result.returncode == 0
    assert "scope=repo" in result.stdout
    assert "authoritative=true" in result.stdout
    records = list((tmp_path / "projects").glob("*/ledgers/user/um-*.md"))
    assert len(records) == 1
    content = records[0].read_text()
    assert 'source_fidelity: "direct_user_statement"' in content
    assert 'truth_status: "user_asserted_unverified"' in content
    assert "confidence:" not in content

    project = next(line.split('"')[1] for line in content.splitlines() if line.startswith("repo:"))
    project_id = next(line.split('"')[1] for line in content.splitlines() if line.startswith("project_id:"))
    recall = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "memory" / "ralph-recall.py"), "repo memory scope marker", "--project", project, "--project-id", project_id, "--workspace-root", str(ROOT), "--json"],
        cwd=ROOT, env={**os.environ, "RALPH_HOME": str(tmp_path)}, text=True, capture_output=True, check=False,
    )
    payload = json.loads(recall.stdout)
    assert recall.returncode == 0
    managed = next(item for item in payload["results"] if item["metadata"].get("memory_id") == records[0].stem)
    assert managed["metadata"]["scope"] == "repo"
    assert managed["metadata"]["authoritative"] == "true"

    intake = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "memory" / "task-intake.py"),
            "--prompt",
            "Use the repo memory scope marker for this task.",
            "--project",
            project,
            "--project-id",
            project_id,
            "--workspace-root",
            str(ROOT),
            "--branch",
            "codex/a-different-branch",
            "--json",
        ],
        cwd=ROOT,
        env={**os.environ, "RALPH_HOME": str(tmp_path)},
        text=True,
        capture_output=True,
        check=False,
    )
    intake_payload = json.loads(intake.stdout)
    assert intake.returncode == 0
    assert "repo memory scope marker" in intake_payload["agent_prompt_context"]["final_prompt"]
    assert "authoritative-memory-layer" in intake_payload["agent_prompt_context"]["final_prompt"]


def test_relevance_threshold_precedes_authority_bonus(tmp_path: Path) -> None:
    created = run_gateway(
        tmp_path,
        "remember",
        "--text",
        "architecture integration sentinel",
        "--scope",
        "global",
        "--authoritative",
    )
    memory_id = receipt_id(created.stdout)
    intake = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "memory" / "task-intake.py"),
            "--prompt",
            "Please update the user profile in architecture docs",
            "--project",
            ROOT.name,
            "--project-id",
            "p-threshold-test",
            "--workspace-root",
            str(ROOT),
            "--branch",
            "main",
            "--json",
        ],
        cwd=ROOT,
        env={**os.environ, "RALPH_HOME": str(tmp_path)},
        text=True,
        capture_output=True,
        check=False,
    )

    payload = json.loads(intake.stdout)
    assert intake.returncode == 0
    assert memory_id not in payload["selected_memory_ids"]
    assert payload["memory_trace"]["rejected_memory"]


def test_global_yellow_memory_forces_local_route(tmp_path: Path) -> None:
    created = run_gateway(
        tmp_path,
        "remember",
        "--text",
        "private repo review architecture integration sentinel review architecture integration",
        "--scope",
        "global",
    )
    memory_id = receipt_id(created.stdout)
    intake = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "memory" / "task-intake.py"),
            "--prompt",
            "Please review the architecture integration sentinel",
            "--project",
            ROOT.name,
            "--project-id",
            "p-global-yellow-test",
            "--workspace-root",
            str(ROOT),
            "--branch",
            "main",
            "--json",
        ],
        cwd=ROOT,
        env={**os.environ, "RALPH_HOME": str(tmp_path)},
        text=True,
        capture_output=True,
        check=False,
    )

    payload = json.loads(intake.stdout)
    assert intake.returncode == 0
    assert any(f"user/{memory_id}.md" in item for item in payload["selected_memory_ids"])
    assert payload["route"] == "local"
    assert payload["reason"] == "global YELLOW memory requires local handling"


def test_forget_is_exact_and_idempotent(tmp_path: Path) -> None:
    created = run_gateway(tmp_path, "remember", "--text", "forget exact marker", "--scope", "global")
    memory_id = receipt_id(created.stdout)
    first = run_gateway(tmp_path, "forget", "--id", memory_id, "--scope", "global")
    second = run_gateway(tmp_path, "forget", "--id", memory_id, "--scope", "global")

    assert first.returncode == second.returncode == 0
    assert "USER_MEMORY_OK_DEPRECATED" in first.stdout
    assert "USER_MEMORY_OK_ALREADY_DEPRECATED" in second.stdout
    assert 'status: "deprecated"' in (tmp_path / "ledgers" / "user" / f"{memory_id}.md").read_text()


def test_deprecated_record_is_not_enumerated_by_recall(tmp_path: Path) -> None:
    created = run_gateway(tmp_path, "remember", "--text", "deprecated recall marker", "--scope", "global")
    memory_id = receipt_id(created.stdout)
    forgotten = run_gateway(tmp_path, "forget", "--id", memory_id, "--scope", "global")
    assert forgotten.returncode == 0

    recall = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "memory" / "ralph-recall.py"),
            "deprecated recall marker",
            "--project",
            ROOT.name,
            "--workspace-root",
            str(ROOT),
            "--json",
        ],
        cwd=ROOT,
        env={**os.environ, "RALPH_HOME": str(tmp_path)},
        text=True,
        capture_output=True,
        check=False,
    )

    assert recall.returncode == 0
    assert memory_id not in recall.stdout


def test_forget_does_not_confuse_body_text_with_record_status(tmp_path: Path) -> None:
    created = run_gateway(
        tmp_path,
        "remember",
        "--text",
        'ordinary note with status: "deprecated" as literal body text',
        "--scope",
        "global",
    )
    memory_id = receipt_id(created.stdout)

    forgotten = run_gateway(tmp_path, "forget", "--id", memory_id, "--scope", "global")

    assert forgotten.returncode == 0
    assert "USER_MEMORY_OK_DEPRECATED" in forgotten.stdout
    assert 'status: "deprecated"' in (tmp_path / "ledgers" / "user" / f"{memory_id}.md").read_text().split("\n---", 1)[0]


def test_red_is_rejected_without_record(tmp_path: Path) -> None:
    result = run_gateway(tmp_path, "remember", "--text", "token" + "=not-stored", "--scope", "global")

    assert result.returncode != 0
    assert result.stdout.strip() == "USER_MEMORY_REJECTED_RED"
    assert not list(tmp_path.rglob("um-*.md"))


def test_classifier_failure_does_not_write(monkeypatch, tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("user_memory_test", GATEWAY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(GATEWAY.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(GATEWAY.parent))
    monkeypatch.setattr(module, "classify_learning", lambda _text: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(module, "ralph_home", lambda: tmp_path)
    args = type("Args", (), {"text": "classifier failure marker", "classification": None, "scope": "global", "authoritative": False, "workspace_root": str(ROOT)})()

    assert module.remember(args) == 3
    assert not list(tmp_path.rglob("um-*.md"))
