from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".codex" / "hooks"))

from shared.autoresearch_observer import (  # noqa: E402
    AutoResearchObserverError,
    observe_post_tool_payload,
    safe_observe_post_tool_payload,
    safe_project_autoresearch_root,
    safe_observation_path,
)


def write_session(workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "autoresearch.md").write_text("# AutoResearch\n", encoding="utf-8")
    config = {
        "entry_type": "config",
        "segment_id": "segment-1",
        "metric": "seconds",
        "direction": "lower",
    }
    (workspace / "autoresearch.jsonl").write_text(json.dumps(config) + "\n", encoding="utf-8")


def test_observer_noops_without_active_session(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = observe_post_tool_payload({"cwd": str(workspace), "output": "METRIC seconds=1\n"})

    assert result is None
    assert not (tmp_path / "ralph" / "projects").exists()


def test_observer_writes_metric_for_active_session(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    workspace = tmp_path / "workspace"
    write_session(workspace)

    result = observe_post_tool_payload(
        {
            "cwd": str(workspace),
            "session_id": "session-1",
            "success": True,
            "tool_input": {"command": "python benchmark.py"},
            "output": "noise\nMETRIC seconds=1.25\n",
        }
    )

    assert result and result["observed"] is True
    path = Path(result["path"])
    event = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["metrics"] == {"seconds": 1.25}
    assert event["segment_id"] == "segment-1"
    assert path.stat().st_mode & 0o777 == 0o600


def test_observer_reads_only_bounded_config_prefix(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    workspace = tmp_path / "workspace"
    write_session(workspace)
    with (workspace / "autoresearch.jsonl").open("a", encoding="utf-8") as handle:
        for _ in range(1000):
            handle.write(json.dumps({"entry_type": "packet", "payload": "x" * 1000}) + "\n")

    result = observe_post_tool_payload({"cwd": str(workspace), "output": "METRIC seconds=2\n"})

    assert result and result["observed"] is True


def test_observer_rejects_red_output_and_runtime_path_escape(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    workspace = tmp_path / "workspace"
    write_session(workspace)
    red_output = "api_" + "key=fixture-value\nMETRIC seconds=1\n"

    result = observe_post_tool_payload({"cwd": str(workspace), "output": red_output})

    assert result == {"observed": False, "reason": "red_output"}
    assert not list((tmp_path / "ralph").glob("projects/*/autoresearch/pending-metrics.jsonl"))

    raw_command = "python benchmark.py --sec" + "ret=abc123"
    command_result = safe_observe_post_tool_payload(
        {
            "cwd": str(workspace),
            "tool_input": {"command": raw_command},
            "output": "METRIC seconds=1\n",
        }
    )

    assert command_result and command_result["observed"] is True
    command_event = json.loads(Path(command_result["path"]).read_text(encoding="utf-8").splitlines()[-1])
    assert "REDACTED" in command_event["command"]
    assert raw_command not in json.dumps(command_event)

    for unsafe in ("../bad", "p-123", "p-zzzzzzzzzzzzzzzz"):
        try:
            safe_project_autoresearch_root(tmp_path / "ralph", unsafe)
        except AutoResearchObserverError:
            pass
        else:
            raise AssertionError(f"accepted unsafe project id {unsafe}")


def test_observer_rejects_symlink_escape_and_unsafe_filename(tmp_path: Path) -> None:
    base = tmp_path / "ralph"
    project_id = "p-0123456789abcdef"
    outside = tmp_path / "outside"
    outside.mkdir()
    project = base / "projects" / project_id
    project.mkdir(parents=True)
    (project / "autoresearch").symlink_to(outside)

    try:
        safe_project_autoresearch_root(base, project_id)
    except AutoResearchObserverError:
        pass
    else:
        raise AssertionError("accepted symlinked autoresearch runtime path")

    symlink_base = tmp_path / "ralph-symlink-base"
    symlink_base.mkdir()
    (symlink_base / "projects").symlink_to(outside)
    try:
        safe_project_autoresearch_root(symlink_base, project_id)
    except AutoResearchObserverError:
        pass
    else:
        raise AssertionError("accepted symlinked projects runtime path")

    base_link = tmp_path / "ralph-home-link"
    base_link.symlink_to(base, target_is_directory=True)
    try:
        safe_project_autoresearch_root(base_link, project_id)
    except AutoResearchObserverError:
        pass
    else:
        raise AssertionError("accepted symlinked runtime root")

    root = tmp_path / "safe"
    root.mkdir()
    root_link = tmp_path / "safe-link"
    root_link.symlink_to(root, target_is_directory=True)
    try:
        safe_observation_path(root_link, "pending-metrics.jsonl")
    except AutoResearchObserverError:
        pass
    else:
        raise AssertionError("accepted symlinked observation root")

    outside_file = outside / "pending-metrics.jsonl"
    outside_file.write_text("", encoding="utf-8")
    (root / "pending-metrics.jsonl").symlink_to(outside_file)
    try:
        safe_observation_path(root, "pending-metrics.jsonl")
    except AutoResearchObserverError:
        pass
    else:
        raise AssertionError("accepted symlinked observation file")

    for unsafe in ("../pending-metrics.jsonl", "pending/metrics.jsonl"):
        try:
            safe_observation_path(root, unsafe)
        except AutoResearchObserverError:
            pass
        else:
            raise AssertionError(f"accepted unsafe filename {unsafe}")
