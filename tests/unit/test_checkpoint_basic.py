from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run_memory(name: str, ralph_home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["RALPH_HOME"] = str(ralph_home)
    env["CODEX_MEMORY_HOME"] = str(ralph_home / "codex-memories-empty")
    env["RALPH_LOCAL_NOTES_ROOTS"] = ""
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "memory" / name), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def latest_json(root: Path) -> dict:
    return json.loads((root / "checkpoints" / "latest.json").read_text(encoding="utf-8"))


def all_checkpoint_text(root: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in root.rglob("*") if path.is_file())


def test_checkpoint_update_writes_json_markdown_archive_and_event(tmp_path: Path) -> None:
    result = run_memory(
        "checkpoint.py",
        tmp_path,
        "--update",
        "--objective",
        "Implement rolling checkpoint core.",
        "--current-phase",
        "Phase 1",
        "--last-verified-state",
        "Plan hash was verified.",
        "--next-action",
        "Add unit tests.",
        "--active-file",
        "scripts/memory/checkpoint.py",
        "--validation-status",
        "partial",
    )

    assert result.returncode == 0, result.stderr
    assert "CHECKPOINT_OK" in result.stdout
    checkpoint = latest_json(tmp_path)
    markdown = (tmp_path / "checkpoints" / "latest.md").read_text(encoding="utf-8")
    assert checkpoint["version"] == 1
    assert checkpoint["classification"] == "YELLOW"
    assert checkpoint["objective"] == "Implement rolling checkpoint core."
    assert checkpoint["next_action"] == "Add unit tests."
    assert checkpoint["validation_status"] == "partial"
    assert len(checkpoint["content_hash"]) == 64
    assert "Continuity checkpoint:" in markdown
    assert "Objective: Implement rolling checkpoint core." in markdown
    assert list((tmp_path / "checkpoints" / "archive").glob("*.json"))
    events = (tmp_path / "checkpoints" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(events[-1])["event"] == "updated"


def test_checkpoint_skips_red_without_leaking_secret_text(tmp_path: Path) -> None:
    secret_text = "token" + "=abc123"
    result = run_memory(
        "checkpoint.py",
        tmp_path,
        "--update",
        "--objective",
        "safe objective",
        "--next-action",
        secret_text,
    )

    assert result.returncode == 0, result.stderr
    assert "CHECKPOINT_SKIPPED_RED" in result.stdout
    assert not (tmp_path / "checkpoints" / "latest.json").exists()
    assert secret_text not in all_checkpoint_text(tmp_path)
    assert "abc123" not in all_checkpoint_text(tmp_path)


def test_checkpoint_render_budget_and_field_truncation(tmp_path: Path) -> None:
    long_objective = " ".join(f"word{i}" for i in range(200))
    result = run_memory(
        "checkpoint.py",
        tmp_path,
        "--update",
        "--objective",
        long_objective,
        "--next-action",
        "Continue with tests.",
    )

    assert result.returncode == 0, result.stderr
    checkpoint = latest_json(tmp_path)
    assert len(checkpoint["objective"]) < len(long_objective)
    assert checkpoint["objective"].endswith("...[truncated]")

    render = run_memory("checkpoint.py", tmp_path, "--render", "--max-words", "20")
    assert render.returncode == 0, render.stderr
    assert len(render.stdout.split()) <= 21
    assert "...[truncated]" in render.stdout


def test_checkpoint_content_hash_is_stable_for_same_operational_state(tmp_path: Path) -> None:
    args = [
        "--update",
        "--objective",
        "Stable objective.",
        "--next-action",
        "Stable next action.",
    ]
    first = run_memory("checkpoint.py", tmp_path, *args)
    first_hash = latest_json(tmp_path)["content_hash"]
    second = run_memory("checkpoint.py", tmp_path, *args)
    second_hash = latest_json(tmp_path)["content_hash"]

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first_hash == second_hash


def test_wakeup_includes_fresh_checkpoint_under_budget(tmp_path: Path) -> None:
    update = run_memory(
        "checkpoint.py",
        tmp_path,
        "--update",
        "--objective",
        "Resume checkpoint work.",
        "--next-action",
        "Run checkpoint unit tests.",
    )
    assert update.returncode == 0, update.stderr

    wakeup = run_memory("wakeup.py", tmp_path)
    assert wakeup.returncode == 0, wakeup.stderr
    assert "## Latest Rolling Checkpoint" in wakeup.stdout
    assert "Objective: Resume checkpoint work." in wakeup.stdout
    assert len(wakeup.stdout.split()) < 1_500


def test_wakeup_omits_stale_checkpoint(tmp_path: Path) -> None:
    update = run_memory(
        "checkpoint.py",
        tmp_path,
        "--update",
        "--objective",
        "Old objective.",
        "--next-action",
        "Old next action.",
    )
    assert update.returncode == 0, update.stderr
    checkpoint_path = tmp_path / "checkpoints" / "latest.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["updated_at"] = (datetime.now(timezone.utc) - timedelta(days=3)).replace(microsecond=0).isoformat()
    checkpoint_path.write_text(json.dumps(checkpoint, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    wakeup = run_memory("wakeup.py", tmp_path)
    assert wakeup.returncode == 0, wakeup.stderr
    assert "## Latest Rolling Checkpoint" not in wakeup.stdout
    assert "Old objective" not in wakeup.stdout


def test_checkpoint_doctor_passes_after_valid_update(tmp_path: Path) -> None:
    update = run_memory("checkpoint.py", tmp_path, "--update", "--objective", "Doctor objective.", "--next-action", "Run doctor.")
    assert update.returncode == 0, update.stderr

    doctor = run_memory("checkpoint.py", tmp_path, "--doctor")
    assert doctor.returncode == 0, doctor.stderr
    assert "CHECKPOINT_DOCTOR_PASS" in doctor.stdout
