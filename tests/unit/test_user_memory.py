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
    assert payload["results"][0]["metadata"]["scope"] == "repo"
    assert payload["results"][0]["metadata"]["authoritative"] == "true"

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


def test_forget_is_exact_and_idempotent(tmp_path: Path) -> None:
    created = run_gateway(tmp_path, "remember", "--text", "forget exact marker", "--scope", "global")
    memory_id = receipt_id(created.stdout)
    first = run_gateway(tmp_path, "forget", "--id", memory_id, "--scope", "global")
    second = run_gateway(tmp_path, "forget", "--id", memory_id, "--scope", "global")

    assert first.returncode == second.returncode == 0
    assert "USER_MEMORY_OK_DEPRECATED" in first.stdout
    assert "USER_MEMORY_OK_ALREADY_DEPRECATED" in second.stdout
    assert 'status: "deprecated"' in (tmp_path / "ledgers" / "user" / f"{memory_id}.md").read_text()


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
