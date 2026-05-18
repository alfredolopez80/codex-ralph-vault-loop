from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROJECT = "codex-ralph-vault-loop"


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
    payload = json.loads(result.stdout)
    assert payload["decision"] == "warn"
    assert "GRADUATION_REVIEW_REQUIRED count=1" in payload["reason"]
    report = latest_project_vault_review(ralph_home)
    assert report["mode"] == "report-only"
    assert report["ask_user"] == 1
    assert not list((vault_dir / "projects" / PROJECT / "decisions").glob("*.md"))


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
