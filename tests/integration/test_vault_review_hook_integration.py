from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROJECT = "codex-ralph-vault-loop"


def project_id_for_path(path: Path) -> str:
    material = f"path:{path.resolve()}".encode("utf-8")
    return f"p-{hashlib.sha256(material).hexdigest()[:16]}"


def env_for(ralph_home: Path, vault_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["RALPH_HOME"] = str(ralph_home)
    env["VAULT_DIR"] = str(vault_dir)
    env["VAULT_PROJECT"] = PROJECT
    env["CODEX_MEMORY_HOME"] = str(ralph_home / "empty-codex-memory")
    env["RALPH_LOCAL_NOTES_ROOTS"] = ""
    env["RALPH_PROMOTION_TIMEOUT_SECONDS"] = "5"
    env["RALPH_VAULT_REVIEW_TIMEOUT_SECONDS"] = "5"
    return env


def run_hook(name: str, ralph_home: Path, vault_dir: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / ".codex" / "hooks" / name)],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env_for(ralph_home, vault_dir),
        check=False,
    )


def run_scheduler(ralph_home: Path, vault_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "memory" / "dream-scheduler.py"),
            "--force",
            "--max-seconds",
            "5",
            "--vault-project",
            PROJECT,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=env_for(ralph_home, vault_dir),
        check=False,
    )


def write_ambiguous_inbox(vault_dir: Path) -> None:
    inbox = vault_dir / "projects" / PROJECT / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "global.md").write_text("Always use this global default behavior for every repo.", encoding="utf-8")


def latest_project_vault_review(ralph_home: Path) -> dict:
    matches = sorted(ralph_home.glob("projects/*/reports/vault-inbox-review/latest.json"))
    assert len(matches) == 1
    return json.loads(matches[0].read_text(encoding="utf-8"))


def test_stop_promotion_hook_runs_vault_review_in_report_only_mode(tmp_path: Path) -> None:
    ralph_home = tmp_path / "ralph"
    vault_dir = tmp_path / "vault"
    write_ambiguous_inbox(vault_dir)

    result = run_hook("stop_memory_promotion_review.py", ralph_home, vault_dir, {"last_assistant_message": "done"})

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    report = latest_project_vault_review(ralph_home)
    assert report["mode"] == "report-only"
    assert report["ask_user"] == 1
    assert not list((vault_dir / "projects" / PROJECT / "decisions").glob("*.md"))


def test_stop_promotion_hook_skips_without_learning_or_inbox(tmp_path: Path) -> None:
    ralph_home = tmp_path / "ralph"
    vault_dir = tmp_path / "vault"

    result = run_hook("stop_memory_promotion_review.py", ralph_home, vault_dir, {"last_assistant_message": "done"})

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert not list(ralph_home.glob("projects/*/reports/memory/promotion-latest.json"))
    assert not list(ralph_home.glob("projects/*/reports/vault-inbox-review/latest.json"))


def test_stop_promotion_hook_runs_for_codex_memory_sources(tmp_path: Path) -> None:
    ralph_home = tmp_path / "ralph"
    vault_dir = tmp_path / "vault"
    codex_memory = tmp_path / "codex-memories"
    codex_memory.mkdir()
    (codex_memory / "MEMORY.md").write_text(
        "Decision: codex memory project convention should be reviewed before promotion.",
        encoding="utf-8",
    )
    env = env_for(ralph_home, vault_dir)
    env["CODEX_MEMORY_HOME"] = str(codex_memory)

    result = subprocess.run(
        [sys.executable, str(ROOT / ".codex" / "hooks" / "stop_memory_promotion_review.py")],
        cwd=ROOT,
        input=json.dumps({"last_assistant_message": "done"}),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    promotion_path = next(ralph_home.glob("projects/*/reports/memory/promotion-latest.json"))
    promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
    assert promotion["review_requested"][0]["source_groups"] == ["codex-memories"]


def test_stop_promotion_hook_runs_for_configured_local_notes_sources(tmp_path: Path) -> None:
    ralph_home = tmp_path / "ralph"
    vault_dir = tmp_path / "vault"
    local_notes = tmp_path / "repo" / ".local-notes" / "reviews"
    local_notes.mkdir(parents=True)
    (local_notes / "future-review.md").write_text(
        "Decision: project local-notes review findings should be considered for memory promotion.",
        encoding="utf-8",
    )
    env = env_for(ralph_home, vault_dir)
    env["RALPH_LOCAL_NOTES_ROOTS"] = str(tmp_path / "repo" / ".local-notes")

    result = subprocess.run(
        [sys.executable, str(ROOT / ".codex" / "hooks" / "stop_memory_promotion_review.py")],
        cwd=ROOT,
        input=json.dumps({"last_assistant_message": "done"}),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    promotion_path = next(ralph_home.glob("projects/*/reports/memory/promotion-latest.json"))
    promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
    assert promotion["review_requested"][0]["source_groups"] == ["local-notes"]


def test_stop_promotion_hook_runs_for_project_handoff_sources(tmp_path: Path) -> None:
    ralph_home = tmp_path / "ralph"
    vault_dir = tmp_path / "vault"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    handoffs = ralph_home / "projects" / project_id_for_path(workspace) / "handoffs"
    handoffs.mkdir(parents=True)
    (handoffs / "latest.md").write_text(
        "Decision: project must keep hook benchmark scoped before memory promotion.",
        encoding="utf-8",
    )

    result = run_hook(
        "stop_memory_promotion_review.py",
        ralph_home,
        vault_dir,
        {"cwd": str(workspace), "last_assistant_message": "done"},
    )

    assert result.returncode == 0, result.stderr
    promotion_path = next(ralph_home.glob("projects/*/reports/memory/promotion-latest.json"))
    promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
    candidates = promotion["auto_promoted"] + promotion["review_requested"]
    assert any(candidate["source_groups"] == ["handoffs"] for candidate in candidates)


def test_dream_scheduler_runs_vault_review_after_success(tmp_path: Path) -> None:
    ralph_home = tmp_path / "ralph"
    vault_dir = tmp_path / "vault"
    write_ambiguous_inbox(vault_dir)

    result = run_scheduler(ralph_home, vault_dir)

    assert result.returncode == 0, result.stderr
    state = json.loads((ralph_home / "reports" / "memory" / "dream-scheduler.json").read_text(encoding="utf-8"))
    assert state["status"] == "success"
    assert "VAULT_INBOX_REVIEW_OK" in state["last_output"]
    report = json.loads((ralph_home / "reports" / "vault-inbox-review" / "latest.json").read_text(encoding="utf-8"))
    assert report["mode"] == "report-only"
