from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".codex" / "hooks" / "post_tool_dispatch.py"


def env_for(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "RALPH_HOME": str(tmp_path / "ralph"),
            "CODEX_MEMORY_HOME": str(tmp_path / "empty-memory"),
            "VAULT_DIR": str(tmp_path / "empty-vault"),
            "RALPH_LOCAL_NOTES_ROOTS": "",
            "CODEX_HOOK_STATE_ROOT": str(tmp_path / "hook-state"),
            "CODEX_SLOP_GUARD_ENABLED": "0",
        }
    )
    return env


def payload(tmp_path: Path, *, tool: str, tool_input: dict | None = None, **extra: object) -> dict:
    result = {
        "hook_event_name": "PostToolUse",
        "session_id": "dispatch-session",
        "turn_id": "turn-1",
        "tool_use_id": "tool-use-1",
        "cwd": str(tmp_path),
        "tool_name": tool,
        "tool_input": tool_input or {},
        "tool_response": {"exit_code": 0, "stdout": "ok"},
        "success": True,
    }
    result.update(extra)
    return result


def run_dispatch(tmp_path: Path, data: dict, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = env_for(tmp_path)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        cwd=ROOT,
        env=env,
        input=json.dumps(data),
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def runtime_files(tmp_path: Path) -> list[Path]:
    root = tmp_path / "ralph"
    return [path for path in root.rglob("*") if path.is_file()] if root.exists() else []


def test_read_only_call_records_compact_telemetry_without_checkpoint(tmp_path: Path) -> None:
    result = run_dispatch(tmp_path, payload(tmp_path, tool="exec_command", tool_input={"cmd": "git status --short"}))
    assert result.returncode == 0
    assert result.stdout == ""
    assert len(read_jsonl(tmp_path / "ralph" / "cost" / "tool-ledger.jsonl")) == 1
    project_dirs = list((tmp_path / "ralph" / "projects").glob("*/checkpoints")) if (tmp_path / "ralph" / "projects").exists() else []
    assert not project_dirs


def test_small_patch_runs_file_line_shaping_checkpoint_and_ledger(tmp_path: Path) -> None:
    target = tmp_path / "small.py"
    target.write_text("print('ok')\n", encoding="utf-8")
    result = run_dispatch(tmp_path, payload(tmp_path, tool="apply_patch", tool_input={"path": str(target)}))
    assert result.returncode == 0
    assert result.stdout == ""
    assert len(read_jsonl(tmp_path / "ralph" / "cost" / "tool-ledger.jsonl")) == 1
    assert list((tmp_path / "ralph" / "projects").glob("*/checkpoints/latest.json"))


def test_large_patch_uses_supported_block_output(tmp_path: Path) -> None:
    target = tmp_path / "large.py"
    target.write_text("x\n" * 351, encoding="utf-8")
    result = run_dispatch(tmp_path, payload(tmp_path, tool="apply_patch", tool_input={"path": str(target)}))
    body = json.loads(result.stdout)
    assert result.returncode == 0
    assert body["decision"] == "block"
    assert set(body) <= {"decision", "reason"}


def test_generated_file_remains_exempt_from_line_block(tmp_path: Path) -> None:
    target = tmp_path / "package-lock.json"
    target.write_text("{}\n" * 400, encoding="utf-8")
    result = run_dispatch(tmp_path, payload(tmp_path, tool="Write", tool_input={"path": str(target)}))
    assert result.returncode == 0
    assert result.stdout == ""


def test_invalid_event_is_fail_open_and_plain_stdout_free(tmp_path: Path) -> None:
    data = payload(tmp_path, tool="exec_command", tool_input={"cmd": "git status"})
    data["hook_event_name"] = "NotARealHookEvent"
    result = run_dispatch(tmp_path, data)
    assert result.returncode == 0
    assert result.stdout == ""


def test_shaping_markdown_is_report_only_by_default(tmp_path: Path) -> None:
    target = tmp_path / "shape.md"
    target.write_text("---\nshaping: true\n---\n# Shape\n", encoding="utf-8")
    result = run_dispatch(tmp_path, payload(tmp_path, tool="Edit", tool_input={"path": str(target)}))
    assert result.returncode == 0
    assert result.stdout == ""
    assert list((tmp_path / "ralph").rglob("shaping-ripple-warnings.jsonl"))


def test_successful_learning_is_a_candidate_and_failed_red_output_is_not_persisted(tmp_path: Path) -> None:
    learned = payload(
        tmp_path,
        tool="Agent",
        output="Decision: keep checkpoint writes atomic.",
    )
    assert run_dispatch(tmp_path, learned).stdout == ""
    assert list((tmp_path / "ralph").rglob("learning-*.md"))

    secret_key = "api_" + "key"
    red = payload(
        tmp_path,
        tool="Agent",
        tool_use_id="tool-use-red",
        output=f"Decision: {secret_key}=fixture-secret",
    )
    result = run_dispatch(tmp_path, red)
    assert result.returncode == 0
    assert secret_key not in "".join(path.read_text(encoding="utf-8") for path in runtime_files(tmp_path))


def test_nested_success_output_can_become_a_bounded_candidate(tmp_path: Path) -> None:
    data = payload(tmp_path, tool="mcp__catalog.write", tool_use_id="nested-learning")
    data.pop("output", None)
    data["tool_response"] = {"exit_code": 0, "result": "Conclusion: nested result was validated."}
    result = run_dispatch(tmp_path, data)
    assert result.returncode == 0
    assert list((tmp_path / "ralph").rglob("learning-*.md"))


def test_duplicate_tool_use_and_write_stdin_alias_are_idempotent(tmp_path: Path) -> None:
    first = payload(tmp_path, tool="exec_command", tool_input={"cmd": "echo done"}, output="Decision: one candidate")
    assert run_dispatch(tmp_path, first).returncode == 0
    duplicate = run_dispatch(tmp_path, first)
    assert duplicate.returncode == 0
    assert duplicate.stdout == ""
    poll = dict(first)
    poll["tool_name"] = "write_stdin"
    poll["parent_tool_use_id"] = "tool-use-1"
    poll["tool_use_id"] = "poll-1"
    assert run_dispatch(tmp_path, poll).returncode == 0
    assert len(read_jsonl(tmp_path / "ralph" / "cost" / "tool-ledger.jsonl")) == 1
    assert len(list((tmp_path / "ralph").rglob("learning-*.md"))) == 1


def test_partial_exec_does_not_suppress_its_terminal_poll(tmp_path: Path) -> None:
    partial = payload(tmp_path, tool="exec_command", tool_input={"cmd": "pytest -q"})
    partial.pop("success")
    partial["tool_response"] = {"session_id": 41, "output": "still running"}
    assert run_dispatch(tmp_path, partial).returncode == 0
    assert not read_jsonl(tmp_path / "ralph" / "cost" / "tool-ledger.jsonl")

    terminal = payload(
        tmp_path,
        tool="write_stdin",
        tool_use_id="poll-terminal",
        parent_tool_use_id="tool-use-1",
        output="Decision: terminal result is now complete",
    )
    assert run_dispatch(tmp_path, terminal).returncode == 0
    assert len(read_jsonl(tmp_path / "ralph" / "cost" / "tool-ledger.jsonl")) == 1
    assert len(list((tmp_path / "ralph").rglob("learning-*.md"))) == 1
    assert run_dispatch(tmp_path, terminal).returncode == 0
    assert len(read_jsonl(tmp_path / "ralph" / "cost" / "tool-ledger.jsonl")) == 1


def test_mixed_shell_command_is_not_classified_as_read_only(tmp_path: Path) -> None:
    target = tmp_path / "mixed.txt"
    data = payload(
        tmp_path,
        tool="exec_command",
        tool_input={"cmd": f"git status --short && touch {target}"},
        tool_use_id="mixed-command",
    )
    assert run_dispatch(tmp_path, data).returncode == 0
    assert list((tmp_path / "ralph" / "projects").glob("*/checkpoints/latest.json"))


def test_corrupt_state_recovers_and_two_processes_do_not_duplicate_ledger(tmp_path: Path) -> None:
    data = payload(tmp_path, tool="Agent", output="Decision: recover dedupe state")
    assert run_dispatch(tmp_path, data).returncode == 0
    state = next((tmp_path / "ralph").rglob("dedupe.json"))
    state.write_text("{broken", encoding="utf-8")
    recovered = run_dispatch(tmp_path, data)
    assert recovered.returncode == 0
    assert list(state.parent.glob("dedupe.json.invalid.*"))

    fresh = payload(tmp_path, tool="apply_patch", tool_input={"path": str(tmp_path / "fresh.py")}, tool_use_id="concurrent")
    (tmp_path / "fresh.py").write_text("x\n", encoding="utf-8")
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: run_dispatch(tmp_path, fresh), range(4)))
    assert all(item.returncode == 0 for item in results)
    ledger = read_jsonl(tmp_path / "ralph" / "cost" / "tool-ledger.jsonl")
    assert sum(item.get("tool", "") == "apply_patch" for item in ledger) == 1


def test_mcp_read_and_test_failure_use_only_relevant_persistence(tmp_path: Path) -> None:
    mcp = payload(tmp_path, tool="mcp__catalog.read", tool_input={"path": "README.md"})
    assert run_dispatch(tmp_path, mcp).stdout == ""
    assert not list((tmp_path / "ralph" / "projects").glob("*/checkpoints/latest.json"))

    failed = payload(
        tmp_path,
        tool="exec_command",
        tool_input={"cmd": "pytest tests/unit -q"},
        success=False,
        tool_use_id="failed-test",
        output="failure summary only",
    )
    result = run_dispatch(tmp_path, failed)
    assert result.returncode == 0
    assert list((tmp_path / "ralph" / "projects").glob("*/checkpoints/latest.json"))
    assert not list((tmp_path / "ralph").rglob("learning-*.md"))


def test_symlink_runtime_fails_open_without_escape(tmp_path: Path) -> None:
    real = tmp_path / "real-runtime"
    real.mkdir()
    linked = tmp_path / "linked-runtime"
    linked.symlink_to(real, target_is_directory=True)
    result = run_dispatch(tmp_path, payload(tmp_path, tool="exec_command", tool_input={"cmd": "git status"}), {"RALPH_HOME": str(linked)})
    assert result.returncode == 0
    assert result.stdout == ""
    assert not list(real.rglob("dedupe.json"))


def test_dedupe_entry_count_is_bounded(tmp_path: Path) -> None:
    for index in range(24):
        data = payload(
            tmp_path,
            tool="exec_command",
            tool_input={"cmd": "git status"},
            tool_use_id=f"bounded-{index}",
        )
        assert run_dispatch(tmp_path, data, {"RALPH_POST_TOOL_DEDUPE_MAX_ENTRIES": "16"}).returncode == 0
    state = next((tmp_path / "ralph").rglob("dedupe.json"))
    entries = json.loads(state.read_text(encoding="utf-8"))["entries"]
    assert len(entries) <= 16
