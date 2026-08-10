from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".codex" / "hooks" / "session_start_dispatch.py"
if str(ROOT / ".codex" / "hooks") not in sys.path:
    sys.path.insert(0, str(ROOT / ".codex" / "hooks"))

from shared.implementation_store import ImplementationStore, resolve_store_paths_local


def _store(root: Path) -> ImplementationStore:
    store = ImplementationStore(resolve_store_paths_local(root))
    store.register_plan(
        "demo",
        plan_path=".ralph/plans/demo.md",
        status="active",
        objective="Keep recovery deterministic.",
        phase="verification",
        next_action="Run focused tests.",
        provenance={
            "git": {"workspace_instance_id": "workspace", "branch": "main", "commit": ""},
            "writer_session_id": "writer",
            "model_family": "unknown",
            "model_source": "unknown",
            "model_verified": False,
            "origin": "implementation-progress",
            "intent": "progress-maintenance",
        },
        operation_id="start-demo",
    )
    return store


def _payload(root: Path, source: str, session: str) -> dict[str, object]:
    return {
        "hook_event_name": "SessionStart",
        "source": source,
        "session_id": session,
        "cwd": str(root),
        "primary_repo_root": str(root),
        "workspace_instance_id": "workspace",
        "model": "gpt-5.6-luna",
        "branch": "main",
        "sha": "abc123",
    }


def _run(root: Path, payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "RALPH_HOME": str(root / "ralph"),
            "RALPH_LOCAL_NOTES_ROOTS": "",
            "CODEX_MEMORY_HOME": str(root / "memory"),
            "RALPH_PROGRESS_LEGACY_FALLBACK": "",
        }
    )
    return subprocess.run(
        [sys.executable, str(HOOK)],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_new_store_session_start_subprocess_matrix_is_local_and_exact_once(tmp_path: Path) -> None:
    _store(tmp_path)

    startup = _run(tmp_path, _payload(tmp_path, "startup", "session-start"))
    assert startup.returncode == 0, startup.stderr
    assert "Implementation progress" in startup.stdout

    retry = _run(tmp_path, _payload(tmp_path, "startup", "session-start"))
    assert retry.returncode == 0, retry.stderr
    assert retry.stdout == ""

    resume = _run(tmp_path, _payload(tmp_path, "resume", "session-resume"))
    assert resume.returncode == 0, resume.stderr
    assert "Implementation progress update" in resume.stdout

    compact = _run(tmp_path, _payload(tmp_path, "compact", "session-compact"))
    assert compact.returncode == 0, compact.stderr
    assert "Implementation progress" in compact.stdout

    clear = _run(tmp_path, _payload(tmp_path, "clear", "session-compact"))
    assert clear.returncode == 0, clear.stderr
    assert clear.stdout == ""
    after_clear = _run(tmp_path, _payload(tmp_path, "startup", "session-compact"))
    assert after_clear.returncode == 0, after_clear.stderr
    assert after_clear.stdout == ""

    ledger = tmp_path / ".local-notes" / "ralph" / "implementation" / "context-emissions.jsonl"
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 3
    event_files = list((tmp_path / "ralph").glob("projects/*/observability/runtime-events.jsonl*"))
    assert event_files
    events = [json.loads(line) for path in event_files for line in path.read_text(encoding="utf-8").splitlines()]
    assert events
    assert all(event.get("child_process_count") == 0 for event in events)
