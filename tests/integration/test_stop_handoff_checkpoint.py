from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STOP_HOOK = ROOT / ".codex" / "hooks" / "stop_persist_memory.py"
CHECKPOINT = ROOT / "scripts" / "memory" / "checkpoint.py"
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.active_context import active_context_from_payload  # noqa: E402


def env_for(ralph_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["RALPH_HOME"] = str(ralph_home)
    env["CODEX_MEMORY_HOME"] = str(ralph_home / "codex-memories-empty")
    env["RALPH_LOCAL_NOTES_ROOTS"] = ""
    return env


def run_stop_hook(ralph_home: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    payload = {"cwd": str(ROOT), **payload}
    return subprocess.run(
        [sys.executable, str(STOP_HOOK)],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env_for(ralph_home),
        check=False,
    )


def run_checkpoint(ralph_home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKPOINT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=env_for(ralph_home),
        check=False,
    )


def latest_handoff(ralph_home: Path) -> str:
    matches = sorted(ralph_home.glob("projects/*/handoffs/latest.md"))
    assert len(matches) == 1
    return matches[0].read_text(encoding="utf-8")


def project_checkpoint_args() -> list[str]:
    context = active_context_from_payload({"cwd": str(ROOT), "session_id": "stop-handoff-test"})
    return [
        "--project",
        context.project_slug,
        "--project-id",
        context.project_id,
        "--workspace-root",
        str(context.workspace_root),
        "--session-id",
        context.session_id,
    ]


def test_stop_handoff_includes_checkpoint_for_short_final_message(tmp_path: Path) -> None:
    update = run_checkpoint(
        tmp_path,
        "--update",
        "--objective",
        "Implement Phase 5 enriched Stop handoff.",
        "--current-phase",
        "Phase 5",
        "--last-verified-state",
        "Focused checkpoint tests passed.",
        "--next-action",
        "Run hook chain validation.",
        "--validation-status",
        "partial",
        *project_checkpoint_args(),
    )
    assert update.returncode == 0, update.stderr

    result = run_stop_hook(tmp_path, {"last_assistant_message": "Done."})

    assert result.returncode == 0, result.stderr
    text = latest_handoff(tmp_path)
    assert "## Rolling Checkpoint" in text
    assert "Objective: Implement Phase 5 enriched Stop handoff." in text
    assert "Next action: Run hook chain validation." in text
    assert "## Final Assistant Message" in text
    assert "Done." in text
    assert "Next:" in text
    assert "Run hook chain validation." in text


def test_stop_handoff_falls_back_without_checkpoint(tmp_path: Path) -> None:
    result = run_stop_hook(tmp_path, {"last_assistant_message": "Plain handoff still works."})

    assert result.returncode == 0, result.stderr
    text = latest_handoff(tmp_path)
    assert "Plain handoff still works." in text
    assert "## Rolling Checkpoint" not in text


def test_stop_handoff_skips_red_final_message(tmp_path: Path) -> None:
    red_text = "token" + "=abc123"
    result = run_stop_hook(tmp_path, {"last_assistant_message": red_text})

    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.glob("projects/*/handoffs/latest.md"))


def test_stop_handoff_omits_red_checkpoint_without_leaking(tmp_path: Path) -> None:
    checkpoints = tmp_path / "checkpoints"
    checkpoints.mkdir(parents=True)
    secret_text = "token" + "=abc123"
    (checkpoints / "latest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "updated_at": "2026-05-18T00:00:00+00:00",
                "status": "active",
                "classification": "RED",
                "objective": secret_text,
                "next_action": secret_text,
                "validation_status": "not_run",
                "active_files": [],
                "commands_run": [],
                "blockers": [],
                "risk_flags": [],
                "source": "manual",
            }
        ),
        encoding="utf-8",
    )

    result = run_stop_hook(tmp_path, {"last_assistant_message": "Safe final message."})

    assert result.returncode == 0, result.stderr
    text = latest_handoff(tmp_path)
    assert "Safe final message." in text
    assert "## Rolling Checkpoint" not in text
    assert secret_text not in text
    assert "abc123" not in text
