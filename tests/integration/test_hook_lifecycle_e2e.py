from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
PROJECT = "codex-ralph-vault-loop"
SESSION_ID = "lifecycle-e2e-session"
RAW_SENTINEL = "RAW_TOOL_OUTPUT_SENTINEL_SHOULD_NOT_PERSIST"
LEARNING_TEXT = "Decision: project checkpoint lifecycle uses runtime-correlated handoffs and ledgers."
CURATED_MARKER = "curated-e2e-lifecycle-marker-39217"
INBOX_MARKER = "inbox-e2e-lifecycle-marker-39217"


def env_for(ralph_home: Path, vault_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["RALPH_HOME"] = str(ralph_home)
    env["CODEX_MEMORY_HOME"] = str(ralph_home / "codex-memories-empty")
    env["RALPH_LOCAL_NOTES_ROOTS"] = ""
    env["VAULT_DIR"] = str(vault_dir)
    env["VAULT_PROJECT"] = PROJECT
    env["CODEX_SESSION_ID"] = SESSION_ID
    env["RALPH_PROMOTION_TIMEOUT_SECONDS"] = "10"
    return env


def run_hook(name: str, ralph_home: Path, vault_dir: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOKS / name)],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env_for(ralph_home, vault_dir),
        check=False,
    )


def run_memory(ralph_home: Path, vault_dir: Path, name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "memory" / name), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=env_for(ralph_home, vault_dir),
        check=False,
    )


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def generated_text(root: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in root.rglob("*") if path.is_file())


def project_root(ralph_home: Path) -> Path:
    roots = sorted(path for path in (ralph_home / "projects").glob("*") if path.is_dir())
    assert len(roots) == 1
    return roots[0]


def latest_checkpoint(ralph_home: Path) -> dict:
    return read_json(project_root(ralph_home) / "checkpoints" / "latest.json")


def project_args(checkpoint: dict) -> list[str]:
    return [
        "--project",
        str(checkpoint["project"]),
        "--project-id",
        str(checkpoint["project_id"]),
        "--workspace-root",
        str(checkpoint["workspace_root"]),
    ]


def test_checkpoint_memory_lifecycle_e2e(tmp_path: Path) -> None:
    ralph_home = tmp_path / "ralph"
    vault_dir = tmp_path / "vault"

    prompt_payload = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": SESSION_ID,
        "prompt": "Implement the lifecycle checkpoint validation path.",
    }
    capture = run_hook("user_prompt_capture.py", ralph_home, vault_dir, prompt_payload)
    prompt = run_hook("continuity_prompt_context.py", ralph_home, vault_dir, prompt_payload)
    assert capture.returncode == 0, capture.stderr
    assert prompt.returncode == 0, prompt.stderr
    assert prompt.stdout == ""
    checkpoint = latest_checkpoint(ralph_home)
    assert checkpoint["objective"] == "Implement the lifecycle checkpoint validation path."

    learning = run_hook("post_tool_extract_memory.py", ralph_home, vault_dir, {"output": LEARNING_TEXT})
    assert learning.returncode == 0, learning.stderr
    assert list((project_root(ralph_home) / "ledgers").glob("learning-*.md"))

    pass_payload = {
        "tool_name": "exec_command",
        "tool_input": {"command": "python3 -m pytest tests/integration/test_hook_lifecycle_e2e.py"},
        "success": True,
        "output": RAW_SENTINEL,
    }
    passed = run_hook("post_tool_checkpoint.py", ralph_home, vault_dir, pass_payload)
    assert passed.returncode == 0, passed.stderr
    checkpoint = latest_checkpoint(ralph_home)
    assert checkpoint["validation_status"] == "pass"
    assert "Command passed:" in checkpoint["last_verified_state"]

    fail_payload = {
        "tool_name": "exec_command",
        "tool_input": {"command": "python3 -m pytest tests/integration/missing_fixture.py"},
        "success": False,
        "output": RAW_SENTINEL,
    }
    failed = run_hook("post_tool_checkpoint.py", ralph_home, vault_dir, fail_payload)
    assert failed.returncode == 0, failed.stderr
    checkpoint = latest_checkpoint(ralph_home)
    assert checkpoint["validation_status"] == "fail"
    assert checkpoint["blockers"][-1] == "Command failed: python3 -m pytest tests/integration/missing_fixture.py"
    assert RAW_SENTINEL not in generated_text(ralph_home)

    active_project_args = project_args(checkpoint)
    first_wakeup = run_memory(ralph_home, vault_dir, "wakeup.py", *active_project_args)
    second_wakeup = run_memory(ralph_home, vault_dir, "wakeup.py", *active_project_args)
    assert first_wakeup.returncode == 0, first_wakeup.stderr
    assert second_wakeup.returncode == 0, second_wakeup.stderr
    assert "## Latest Rolling Checkpoint" in first_wakeup.stdout
    assert "## Latest Rolling Checkpoint" not in second_wakeup.stdout

    stop = run_hook("stop_persist_memory.py", ralph_home, vault_dir, {"last_assistant_message": LEARNING_TEXT})
    assert stop.returncode == 0, stop.stderr
    handoff = (project_root(ralph_home) / "handoffs" / "latest.md").read_text(encoding="utf-8")
    assert "## Rolling Checkpoint" in handoff
    assert LEARNING_TEXT in handoff
    assert RAW_SENTINEL not in handoff
    handoff_wakeup = run_hook("session_start_wakeup.py", ralph_home, vault_dir, {"session_id": SESSION_ID})
    assert handoff_wakeup.returncode == 0, handoff_wakeup.stderr
    assert "## Latest Handoff" in handoff_wakeup.stdout
    assert "Handoff reinjection: full within 15% budget" in handoff_wakeup.stdout
    assert LEARNING_TEXT in handoff_wakeup.stdout

    promotion = run_hook("stop_memory_promotion_review.py", ralph_home, vault_dir, {"last_assistant_message": LEARNING_TEXT})
    assert promotion.returncode == 0, promotion.stderr
    assert (project_root(ralph_home) / "reports" / "memory" / "dream-latest.json").is_file()
    assert (project_root(ralph_home) / "reports" / "memory" / "promotion-latest.json").is_file()
    assert LEARNING_TEXT in (project_root(ralph_home) / "layers" / "L2_project_rules.md").read_text(encoding="utf-8")

    curated = vault_dir / "projects" / PROJECT / "wiki" / "lifecycle.md"
    curated.parent.mkdir(parents=True, exist_ok=True)
    curated.write_text(f"{CURATED_MARKER}: default recall should find this.\n", encoding="utf-8")
    inbox = vault_dir / "projects" / PROJECT / "inbox" / "candidate.md"
    inbox.parent.mkdir(parents=True, exist_ok=True)
    inbox.write_text(f"{INBOX_MARKER}: default recall must not read this.\n", encoding="utf-8")

    recall_curated = run_memory(
        ralph_home,
        vault_dir,
        "ralph-recall.py",
        CURATED_MARKER,
        "--project",
        PROJECT,
        "--project-id",
        str(checkpoint["project_id"]),
        "--limit",
        "20",
        "--json",
    )
    recall_inbox_default = run_memory(
        ralph_home,
        vault_dir,
        "ralph-recall.py",
        INBOX_MARKER,
        "--project",
        PROJECT,
        "--project-id",
        str(checkpoint["project_id"]),
        "--limit",
        "20",
        "--json",
    )
    recall_inbox_raw = run_memory(
        ralph_home,
        vault_dir,
        "ralph-recall.py",
        INBOX_MARKER,
        "--project",
        PROJECT,
        "--project-id",
        str(checkpoint["project_id"]),
        "--include-raw",
        "--limit",
        "20",
        "--json",
    )
    assert recall_curated.returncode == 0, recall_curated.stderr
    assert recall_inbox_default.returncode == 0, recall_inbox_default.stderr
    assert recall_inbox_raw.returncode == 0, recall_inbox_raw.stderr
    curated_results = json.loads(recall_curated.stdout)["results"]
    inbox_default_results = json.loads(recall_inbox_default.stdout)["results"]
    inbox_raw_results = json.loads(recall_inbox_raw.stdout)["results"]
    assert any(CURATED_MARKER in result["preview"] and "lifecycle.md" in result["path"] for result in curated_results)
    assert inbox_default_results == []
    assert any(INBOX_MARKER in result["preview"] and "candidate.md" in result["path"] for result in inbox_raw_results)
    assert RAW_SENTINEL not in generated_text(ralph_home)
    assert RAW_SENTINEL not in recall_curated.stdout
    assert RAW_SENTINEL not in recall_inbox_default.stdout

    large_message = " ".join(f"w{i:03d}" for i in range(360))
    large_stop = run_hook("stop_persist_memory.py", ralph_home, vault_dir, {"last_assistant_message": large_message})
    assert large_stop.returncode == 0, large_stop.stderr
    large_handoff = (project_root(ralph_home) / "handoffs" / "latest.md").read_text(encoding="utf-8")
    assert "w000" in large_handoff
    assert "w359" in large_handoff
    large_wakeup = run_hook("session_start_wakeup.py", ralph_home, vault_dir, {"session_id": SESSION_ID})
    assert large_wakeup.returncode == 0, large_wakeup.stderr
    assert "Handoff reinjection: compacted over 15% budget" in large_wakeup.stdout
    assert "w000" in large_wakeup.stdout
    assert "w359" not in large_wakeup.stdout
