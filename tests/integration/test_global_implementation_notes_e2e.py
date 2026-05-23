from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "scripts" / "setup" / "install-global.sh"
CREATE = ROOT / "scripts" / "plans" / "create-implementation-notes.py"
APPEND = ROOT / "scripts" / "plans" / "append-implementation-note.py"


def run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None, input_text: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, input=input_text, text=True, capture_output=True, check=False)


def git(cwd: Path, *args: str) -> str:
    result = run(["git", *args], cwd=cwd)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def make_repo_with_worktree(tmp_path: Path, home: Path) -> tuple[Path, Path]:
    primary = tmp_path / "primary" / "sample-project"
    active = home / ".codex" / "worktrees" / "fixture" / "sample-project"
    primary.mkdir(parents=True)
    git(primary, "init")
    git(primary, "config", "user.email", "test@example.invalid")
    git(primary, "config", "user.name", "Test User")
    (primary / "README.md").write_text("# sample\n", encoding="utf-8")
    git(primary, "add", "README.md")
    git(primary, "commit", "-m", "init")
    active.parent.mkdir(parents=True)
    git(primary, "worktree", "add", "--detach", str(active), "HEAD")
    return primary, active


def write_plan(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# E2E Plan\n\n"
        "Implementation notes required: yes\n"
        "Implementation notes status: pending\n"
        "Plan approval status: approved\n",
        encoding="utf-8",
    )


def env_for(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["RALPH_HOME"] = str(home / ".ralph-codex")
    env["CODEX_MEMORY_HOME"] = str(home / ".codex-memories-empty")
    env["RALPH_LOCAL_NOTES_ROOTS"] = ""
    return env


def test_global_installed_implementation_notes_flow_updates_project_index(tmp_path: Path) -> None:
    home = tmp_path / "home"
    env = env_for(home)
    install = run(["bash", str(INSTALL), "--install", "--with-agents", "--allow-worktree-source"], cwd=ROOT, env=env)
    assert install.returncode == 0, install.stderr
    installed_hook = home / ".codex" / "hooks" / "implementation_notes_guard.py"
    hooks_json = home / ".codex" / "hooks.json"
    agents_md = home / ".codex" / "AGENTS.md"
    assert installed_hook.is_file()
    assert str(installed_hook) in hooks_json.read_text(encoding="utf-8")
    assert "implementation-index.json" in agents_md.read_text(encoding="utf-8")
    assert (home / ".codex" / "hooks" / ".ralph-repo-root").read_text(encoding="utf-8").strip() == str(ROOT)

    primary, active = make_repo_with_worktree(tmp_path, home)
    source_plan = active / ".ralph" / "plans" / "e2e-plan.md"
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
    canonical_plan = primary / ".ralph" / "plans" / "e2e-plan.md"
    notes = primary / ".ralph" / "plans" / "e2e-plan-implementation-notes.html"
    assert canonical_plan.is_file()
    assert notes.is_file()
    active_index = json.loads((primary / ".ralph" / "plans" / "implementation-index.json").read_text(encoding="utf-8"))
    assert active_index["plans"][0]["status"] == "active"
    assert active_index["plans"][0]["commits"] == []
    html = notes.read_text(encoding="utf-8")
    assert "Content-Security-Policy" in html
    assert "style-src 'unsafe-inline'" in html
    assert "<script" not in html

    appended = run(
        [
            sys.executable,
            str(APPEND),
            "--notes",
            str(notes),
            "--category",
            "decision",
            "--decision",
            "Finalize through the globally installed Stop hook.",
            "--reason",
            "The e2e path should prove installed global behavior, not only repo-local imports.",
            "--impact",
            "The canonical project index becomes the business signal.",
            "--active-root",
            str(active),
            "--primary-root",
            str(primary),
        ],
        cwd=ROOT,
        env=env,
    )
    assert appended.returncode == 0, appended.stderr

    payload = {
        "hook_event_name": "Stop",
        "session_id": "global-e2e-session",
        "cwd": str(active),
        "plan_approved": True,
        "last_assistant_message": f"Implemented plan: [{source_plan.relative_to(active)}]({source_plan})",
    }
    stopped = run([sys.executable, str(installed_hook)], cwd=active, env=env, input_text=json.dumps(payload))
    assert stopped.returncode == 0, stopped.stderr
    assert stopped.stdout == ""

    implemented_index = json.loads((primary / ".ralph" / "plans" / "implementation-index.json").read_text(encoding="utf-8"))
    entry = implemented_index["plans"][0]
    assert entry["status"] == "implemented"
    assert entry["plan"] == ".ralph/plans/e2e-plan.md"
    assert entry["notes"] == ".ralph/plans/e2e-plan-implementation-notes.html"
    assert git(active, "rev-parse", "HEAD") in entry["commits"]
    rendered = (primary / ".ralph" / "plans" / "implementation-index.md").read_text(encoding="utf-8")
    assert "e2e-plan.md" in rendered
    assert "implemented" in rendered

    example_payload = {
        "hook_event_name": "Stop",
        "session_id": "global-e2e-example-session",
        "cwd": str(active),
        "last_assistant_message": "Example: /Users/example/project/.ralph/plans/plan.md",
    }
    example = run([sys.executable, str(installed_hook)], cwd=active, env=env, input_text=json.dumps(example_payload))
    assert example.returncode == 0, example.stderr
    assert example.stdout == ""
