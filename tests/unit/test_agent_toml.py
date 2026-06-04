from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / ".codex" / "agents"


REQUIRED_AGENTS = {
    "ralph-coder",
    "ralph-reviewer",
    "ralph-tester",
    "ralph-security",
    "ralph-vault-curator",
    "ralph-openclaw-fast",
    "ralph-zai-counterpart",
    "ralph-minimax-fast",
    "ralph-search-researcher",
    "ralph-vision-analyst",
    "ralph-evaluator",
    "thermo-nuclear-code-quality-review",
}


SECRET_PATTERN = re.compile(
    "|".join(
        [
            r"Z_AI_" + r"API_KEY\s*=",
            r"MINIMAX_" + r"API_KEY\s*=",
            r"s" + r"k-",
            r"BEGIN " + r"(RSA|OPENSSH|PRIVATE)",
        ]
    ),
    re.IGNORECASE,
)
DIRECT_PROVIDER_PATTERN = re.compile(
    r"model_provider\s*=\s*[\"']?(zai|minimax)|\[model_providers\.(zai|minimax)\]",
    re.IGNORECASE,
)


def agent_files() -> list[Path]:
    return sorted(AGENTS.glob("*.toml"))


def test_required_agents_exist() -> None:
    names = {path.stem for path in agent_files()}
    assert REQUIRED_AGENTS <= names


def test_agent_toml_shape_and_names() -> None:
    for path in agent_files():
        text = path.read_text()
        data = tomllib.loads(text)
        assert data["name"] == path.stem
        assert isinstance(data.get("description"), str) and data["description"].strip()
        assert isinstance(data.get("developer_instructions"), str) and data["developer_instructions"].strip()
        assert data.get("sandbox_mode") in {"read-only", "workspace-write"}
        assert "Codex main decides" in data["developer_instructions"]


def test_agents_do_not_define_external_model_providers_or_secrets() -> None:
    for path in agent_files():
        text = path.read_text()
        assert not SECRET_PATTERN.search(text), path
        assert not DIRECT_PROVIDER_PATTERN.search(text), path


def test_external_agents_use_mcp_policy_language() -> None:
    external = [
        "ralph-openclaw-fast",
        "ralph-zai-counterpart",
        "ralph-minimax-fast",
        "ralph-search-researcher",
        "ralph-vision-analyst",
    ]
    for name in external:
        text = (AGENTS / f"{name}.toml").read_text()
        assert "MCP" in text or "MCPs" in text
        assert "RED" in text
        lowered = text.lower()
        assert "direct" in lowered and ("provider" in lowered or "profile" in lowered)


def test_codex_config_uses_repo_local_sfw_wrapper_for_stdio_mcp() -> None:
    config = tomllib.loads((ROOT / ".codex" / "config.toml").read_text(encoding="utf-8"))
    servers = config["mcp_servers"]
    for name in ["zai_vision", "minimax_coding_tools"]:
        command = servers[name]["command"]
        assert command == "scripts/setup/sfw"
        wrapper = ROOT / command
        assert wrapper.is_file()
        assert os.access(wrapper, os.X_OK)
