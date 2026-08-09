from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".codex" / "hooks" / "session_start_wakeup.py"
DISPATCH = ROOT / ".codex" / "hooks" / "session_start_dispatch.py"


def run_session(tmp_path: Path, payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["RALPH_HOME"] = str(tmp_path / "ralph")
    env["VAULT_DIR"] = str(tmp_path / "vault")
    env["RALPH_LOCAL_NOTES_ROOTS"] = ""
    return subprocess.run(
        [sys.executable, str(HOOK)],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=10,
    )


def base_payload(source: str, session_id: str = "session-source") -> dict[str, object]:
    return {
        "hook_event_name": "SessionStart",
        "source": source,
        "session_id": session_id,
        "cwd": str(ROOT),
        "model": "gpt-5.6-sol",
        "branch": "phase-11",
        "sha": "abc123",
        "selected_memory_ids": ["sentinel-green"],
        "route": "local",
    }


def test_all_sources_are_incremental_and_output_is_bounded(tmp_path: Path) -> None:
    startup = run_session(tmp_path, base_payload("startup"))
    assert startup.returncode == 0, startup.stderr
    assert len(startup.stdout.encode("utf-8")) <= 800
    resume = run_session(tmp_path, base_payload("resume"))
    assert resume.returncode == 0, resume.stderr
    assert resume.stdout == ""
    compact = run_session(tmp_path, base_payload("compact"))
    assert compact.returncode == 0, compact.stderr
    assert "source=compact" in compact.stdout
    assert len(compact.stdout.encode("utf-8")) <= 800
    clear = run_session(tmp_path, base_payload("clear"))
    assert clear.returncode == 0, clear.stderr
    assert clear.stdout == ""


def test_fast_path_has_no_heavy_child_or_raw_transcript_and_cache_is_metadata_only(tmp_path: Path) -> None:
    sentinel = "RAW_SESSION_TRANSCRIPT_SENTINEL_11"
    result = run_session(tmp_path, {**base_payload("startup", "raw-session"), "prompt": sentinel})
    assert result.returncode == 0, result.stderr
    dispatch_source = DISPATCH.read_text(encoding="utf-8")
    assert "import subprocess" not in dispatch_source
    assert "subprocess.run" not in dispatch_source
    assert "dream-scheduler.py" not in dispatch_source
    assert sentinel not in result.stdout
    state_files = list((tmp_path / "ralph").glob("projects/*/session-context/state.json"))
    assert state_files
    assert sentinel not in state_files[0].read_text(encoding="utf-8")
