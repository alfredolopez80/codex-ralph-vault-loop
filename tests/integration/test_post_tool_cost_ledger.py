from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".codex" / "hooks" / "post_tool_cost_ledger.py"
DISPATCHER = ROOT / ".codex" / "hooks" / "global_hook_dispatch.py"


def test_post_tool_cost_ledger_records_bounded_local_attribution(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["RALPH_HOME"] = str(tmp_path)
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "exec_command",
        "tool_response": {"stdout": "x" * 20_000},
        "success": True,
    }

    result = subprocess.run(
        [sys.executable, str(HOOK)],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    path = tmp_path / "cost" / "tool-ledger.jsonl"
    ledger_text = path.read_text(encoding="utf-8")
    record = json.loads(ledger_text.splitlines()[-1])
    assert record["event"] == "PostToolUse"
    assert record["hook_role"] == "post_tool_cost_ledger"
    assert record["source_scope"] == "project"
    assert record["duplicate_suppressed"] is False
    assert record["tool_family"] == "command"
    assert record["output_chars"] == 12_000
    assert record["output_truncated"] is True
    assert record["estimated_context_units"] == 3_000
    assert record["subscription_usage_measured"] is False
    assert "x" * 200 not in ledger_text


def test_global_dispatcher_marks_fallback_cost_observer_scope(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env = os.environ.copy()
    env["RALPH_HOME"] = str(tmp_path / "ralph")
    payload = {
        "hook_event_name": "PostToolUse",
        "cwd": str(workspace),
        "session_id": "global-cost-ledger",
        "tool_name": "exec_command",
        "tool_response": {"stdout": "ok"},
        "success": True,
    }

    result = subprocess.run(
        [sys.executable, str(DISPATCHER), "--event", "PostToolUse", "--role", "post_tool_cost_ledger"],
        cwd=workspace,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    path = Path(env["RALPH_HOME"]) / "cost" / "tool-ledger.jsonl"
    record = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["source_scope"] == "global"
    assert record["output_chars"] == 2
