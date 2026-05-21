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
    assert data["intent"] == "logs"
    assert data["lane"] == "minimax-fast"
    assert data["protocol_route"] == "mcp:minimax-fast"
    assert data["tool"] == "ralph_coding_models.minimax_agentic_fast"
    assert data["model"] == "MiniMax-M2.7-highspeed"
    assert data["route_decision"]["verification"]
    assert data["external_mcp_brief"]["tool"] == "MiniMax"


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
    assert data["intent"] == "architecture"
    assert data["lane"] == "zai-deep"
    assert data["protocol_route"] == "mcp:zai-deep"
    assert data["tool"] == "ralph_coding_models.zai_coding_deep"
    assert data["model"] == "GLM-5.1"
    assert data["external_mcp_brief"]["role"] == "debug analyst"


def test_route_task_spec_review_uses_zai_deep_intent_lane() -> None:
    result = run_script("route-task.py", "--task-type", "spec-review", "--complexity", "5", "--sensitivity", "yellow")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["intent"] == "spec-review"
    assert data["lane"] == "zai-deep"
    assert data["tool"] == "ralph_coding_models.zai_coding_deep"
    assert data["external_mcp_brief"]["role"] == "spec reviewer"


def test_route_task_research_url_and_repo_use_zai_official_lanes() -> None:
    research = json.loads(run_script("route-task.py", "--task-type", "research", "--complexity", "3", "--sensitivity", "green").stdout)
    url = json.loads(run_script("route-task.py", "--task-type", "url-reading", "--complexity", "3", "--sensitivity", "green").stdout)
    repo = json.loads(run_script("route-task.py", "--task-type", "repo-reading", "--complexity", "3", "--sensitivity", "green").stdout)

    assert research["lane"] == "zai-search"
    assert research["tool"] == "zai_web_search.web_search_prime"
    assert url["lane"] == "zai-reader"
    assert url["tool"] == "zai_web_reader.webReader"
    assert repo["lane"] == "zai-repo"
    assert repo["tool"] == "zai_zread.search_doc"


def test_route_task_claim_vision_and_high_risk_lanes() -> None:
    claim = json.loads(run_script("route-task.py", "--task-type", "claim-adjudication", "--complexity", "5", "--sensitivity", "yellow").stdout)
    vision = json.loads(run_script("route-task.py", "--task-type", "quick_image", "--complexity", "2", "--sensitivity", "green").stdout)
    high_risk = json.loads(run_script("route-task.py", "--task-type", "architecture", "--complexity", "8", "--sensitivity", "yellow").stdout)

    assert claim["lane"] == "zai-deep"
    assert claim["external_mcp_brief"]["role"] == "claim adjudicator"
    assert vision["lane"] == "minimax-vision"
    assert vision["tool"] == "minimax_coding_tools.understand_image"
    assert high_risk["route"] == "codex_main_with_gates"
    assert high_risk["lane"] == "zai-deep"
    assert high_risk["tool"] == "ralph_coding_models.zai_coding_deep"
    assert high_risk["requires_codex_synthesis"] is True


def test_route_task_unknown_intent_defaults_local() -> None:
    result = run_script("route-task.py", "--task-type", "unknown_task", "--complexity", "4", "--sensitivity", "green")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["intent"] == "unknown-task"
    assert data["lane"] == "local"
    assert data["protocol_route"] == "local"
    assert data["tool"] is None


def test_route_task_red_blocks_externalization() -> None:
    result = run_script("route-task.py", "--task-type", "code_review", "--complexity", "4", "--sensitivity", "red")
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["blocked"] is True
    assert data["protocol_route"] == "local"
    assert data["intent"] == "implementation-support"
    assert data["lane"] == "local"
    assert data["route"] == "codex_main_local"
    assert data["tool"] is None


def test_route_task_blocks_green_content_with_secret_marker() -> None:
    text = "api_key" + "=fixture-value"
    result = run_script(
        "route-task.py",
        "--task-type",
        "code_review",
        "--complexity",
        "4",
        "--sensitivity",
        "green",
        "--text",
        text,
    )
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["blocked"] is True
    assert data["sensitivity"] == "RED"
    assert data["lane"] == "local"
    assert data["tool"] is None
    assert text not in result.stdout
    assert data["sensitive_findings"]


def test_redact_for_external_removes_and_blocks_secret_like_values() -> None:
    text = "secret" + "=abc123"
    result = run_script("redact-for-external.py", "--json", "--text", text)
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["changed"] is True
    assert data["allowed_external"] is False
    assert data["classification"] == "RED"
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
    assert line["decision"]["protocol_route"] == "mcp:minimax-fast"
    assert line["decision"]["intent"] == "logs"
    assert line["decision"]["route_decision"]["route"] == "minimax-fast"


def test_policy_surfaces_preserve_codex_owner_and_generation_boundary() -> None:
    surfaces = [
        ROOT / "AGENTS.md",
        ROOT / ".agents" / "skills" / "model-router" / "SKILL.md",
        ROOT / ".agents" / "skills" / "cost-router" / "SKILL.md",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in surfaces)
    assert "Codex main" in text
    assert "direct Codex `model_provider`" in text
    assert "EXTERNAL_MCP_BRIEF" in text
    assert "Intent-Based" in text or "intent-first" in text
    assert "GPT Images 2" in text
    assert "Never use Z.ai or MiniMax for image generation" in text or "Do not use Z.ai or MiniMax for image" in text
    assert "[model_providers.zai]" not in text
    assert "[model_providers.minimax]" not in text
