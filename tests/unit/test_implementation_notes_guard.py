from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

import implementation_notes_guard as guard
from implementation_notes_lib import GitMetadataError, ImplementationNotesError


def test_guard_fails_open_when_git_metadata_lookup_is_unavailable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        guard,
        "read_hook_input",
        lambda: {"hook_event_name": "Stop", "cwd": str(tmp_path), "session_id": "git-failure"},
    )

    def unavailable(*_args, **_kwargs):
        raise GitMetadataError("could not resolve Git metadata for repository")

    monkeypatch.setattr(guard, "resolve_roots", unavailable)
    emitted: list[dict[str, object]] = []
    monkeypatch.setattr(guard, "write_json", emitted.append)

    assert guard.main() == 0
    assert emitted == []


def test_guard_does_not_treat_user_error_text_as_git_runtime_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        guard,
        "read_hook_input",
        lambda: {"hook_event_name": "Stop", "cwd": str(tmp_path), "session_id": "path-error"},
    )

    def invalid_plan(*_args, **_kwargs):
        raise ImplementationNotesError("notes path contains text: could not resolve Git metadata")

    monkeypatch.setattr(guard, "resolve_roots", invalid_plan)
    emitted: list[dict[str, object]] = []
    monkeypatch.setattr(guard, "write_json", emitted.append)

    assert guard.main() == 0
    assert emitted == [{"decision": "block", "reason": "Implementation notes guard could not validate plan: notes path contains text: could not resolve Git metadata"}]
