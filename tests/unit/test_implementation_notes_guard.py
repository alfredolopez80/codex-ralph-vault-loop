from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

import implementation_notes_guard as guard
from implementation_notes_lib import ImplementationNotesError


def test_guard_fails_open_when_git_metadata_lookup_is_unavailable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        guard,
        "read_hook_input",
        lambda: {"hook_event_name": "Stop", "cwd": str(tmp_path), "session_id": "git-failure"},
    )

    def unavailable(*_args, **_kwargs):
        raise ImplementationNotesError("could not resolve Git metadata for repository")

    monkeypatch.setattr(guard, "resolve_roots", unavailable)
    emitted: list[dict[str, object]] = []
    monkeypatch.setattr(guard, "write_json", emitted.append)

    assert guard.main() == 0
    assert emitted == []
