from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COST = ROOT / "scripts" / "cost"


def run_script(name: str, *args: str, ralph_home: Path | None = None, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if ralph_home is not None:
        env["RALPH_HOME"] = str(ralph_home)
    return subprocess.run(
        [sys.executable, str(COST / name), *args],
        cwd=ROOT,
        input=input_text,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_route_task_outputs_json_for_green_fast_logs() -> None:
    result = run_script("route-task.py", "--task-type", "log_summary", "--complexity", "1", "--sensitivity", "green")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["allowed"] is True
    assert data["tool"] == "ralph_coding_models.minimax_agentic_fast"
    assert data["model"] == "MiniMax-M2.7-highspeed"


def test_route_task_yellow_architecture_uses_glm_deep() -> None:
    result = run_script(
        "route-task.py",
        "--task-type",
        "architecture_counterpart",
        "--complexity",
        "5",
        "--sensitivity",
        "yellow",
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["tool"] == "ralph_coding_models.zai_coding_deep"
    assert data["model"] == "GLM-5.1"


def test_route_task_red_blocks_externalization() -> None:
    result = run_script("route-task.py", "--task-type", "code_review", "--complexity", "4", "--sensitivity", "red")
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["blocked"] is True
    assert data["route"] == "codex_main_local"
    assert data["tool"] is None


def test_redact_for_external_removes_secret_like_values() -> None:
    text = "secret" + "=abc123"
    result = run_script("redact-for-external.py", "--json", "--text", text)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["changed"] is True
    assert text not in data["redacted"]


def test_estimate_context_outputs_counts() -> None:
    result = run_script("estimate-context.py", "--text", "alpha beta")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["words"] == 2
    assert data["estimated_tokens"] >= 1


def test_ledger_writes_jsonl(tmp_path: Path) -> None:
    result = run_script(
        "ledger.py",
        "--task-type",
        "log_summary",
        "--complexity",
        "1",
        "--sensitivity",
        "green",
        ralph_home=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    path = tmp_path / "cost" / "routing-ledger.jsonl"
    assert path.is_file()
    line = json.loads(path.read_text().splitlines()[0])
    assert line["decision"]["tool"] == "ralph_coding_models.minimax_agentic_fast"
