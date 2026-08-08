from __future__ import annotations

import tomllib
import importlib.util
import re
import sys
from pathlib import Path

from scripts.cost._cost_common import LANE_TO_TOOL


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / ".codex" / "config.toml"
MIGRATION = ROOT / "docs" / "migration" / "mcp-tool-names.md"


_CHECKER_SPEC = importlib.util.spec_from_file_location(
    "check_mcp_config", ROOT / "scripts" / "model-router" / "check_mcp_config.py"
)
assert _CHECKER_SPEC and _CHECKER_SPEC.loader
check_mcp_config = importlib.util.module_from_spec(_CHECKER_SPEC)
sys.modules[_CHECKER_SPEC.name] = check_mcp_config
_CHECKER_SPEC.loader.exec_module(check_mcp_config)


def test_project_config_has_one_canonical_server_per_endpoint() -> None:
    report = check_mcp_config.inspect_config(check_mcp_config.load_config(CONFIG))
    assert report["active_server_count"] == 6
    assert report["enabled_tool_count"] == report["enabled_tool_unique_count"] == 21
    assert report["duplicate_endpoint_count"] == 0
    assert report["duplicate_schema_count"] == 0
    assert report["active_legacy_aliases"] == []
    assert report["errors"] == []


def test_enabled_tools_are_unique_and_generation_tool_is_not_exposed() -> None:
    data = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    for server in data["mcp_servers"].values():
        tools = server.get("enabled_tools", [])
        assert len(tools) == len(set(tools))
    assert "ui_to_artifact" not in data["mcp_servers"]["zai_vision"]["enabled_tools"]


def test_active_references_use_canonical_names_and_migration_table_covers_legacy() -> None:
    active_paths = (
        ROOT / ".agents" / "skills" / "model-router" / "SKILL.md",
        ROOT / ".agents" / "skills" / "research" / "SKILL.md",
        ROOT / ".codex" / "agents" / "ralph-search-researcher.toml",
        ROOT / "scripts" / "cost" / "_cost_common.py",
        ROOT / "scripts" / "setup" / "install-global.sh",
        ROOT / "scripts" / "setup" / "doctor-global.sh",
    )
    migration = MIGRATION.read_text(encoding="utf-8")
    for alias in check_mcp_config.LEGACY_ALIASES:
        assert alias in migration
        pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(alias)}(?![A-Za-z0-9_])")
        assert all(not pattern.search(path.read_text(encoding="utf-8")) for path in active_paths)


def test_canonical_router_tools_resolve_to_declared_enabled_tools() -> None:
    data = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    for lane in ("zai-search", "zai-reader", "zai-repo"):
        qualified = LANE_TO_TOOL[lane]
        server, tool = qualified.split(".", 1)
        assert tool in data["mcp_servers"][server]["enabled_tools"]


def test_duplicate_endpoint_and_schema_are_rejected(tmp_path: Path) -> None:
    config = tmp_path / "duplicate.toml"
    config.write_text(
        """
[mcp_servers.zai_web_search]
url = "https://example.invalid/search"
enabled_tools = ["web_search_prime"]

[mcp_servers.web-search-prime]
url = "https://example.invalid/search"
enabled_tools = ["web_search_prime"]
""".strip(),
        encoding="utf-8",
    )
    report = check_mcp_config.inspect_config(check_mcp_config.load_config(config))
    assert any("legacy alias is active" in error for error in report["errors"])
    assert report["duplicate_endpoint_count"] == 1
    assert report["duplicate_schema_count"] == 1


def test_disabled_legacy_alias_is_not_active(tmp_path: Path) -> None:
    config = tmp_path / "disabled.toml"
    config.write_text(
        """
[mcp_servers.zai_web_search]
url = "https://example.invalid/search"
enabled_tools = ["web_search_prime"]

[mcp_servers.web-search-prime]
enabled = false
url = "https://example.invalid/search"
enabled_tools = ["web_search_prime"]
""".strip(),
        encoding="utf-8",
    )
    report = check_mcp_config.inspect_config(check_mcp_config.load_config(config))
    assert report["active_legacy_aliases"] == []
    assert report["duplicate_endpoint_count"] == 0
    assert report["errors"] == []


def test_repeated_enabled_tool_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "repeated.toml"
    config.write_text(
        """
[mcp_servers.zai_web_search]
url = "https://example.invalid/search"
enabled_tools = ["web_search_prime", "web_search_prime"]
""".strip(),
        encoding="utf-8",
    )
    report = check_mcp_config.inspect_config(check_mcp_config.load_config(config))
    assert any("repeats an enabled tool" in error for error in report["errors"])


def test_noncanonical_active_server_name_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "unknown.toml"
    config.write_text(
        """
[mcp_servers.web_search]
url = "https://example.invalid/search"
enabled_tools = ["web_search_prime"]
""".strip(),
        encoding="utf-8",
    )
    report = check_mcp_config.inspect_config(check_mcp_config.load_config(config))
    assert any("noncanonical active server name" in error for error in report["errors"])


def test_project_and_global_fixture_reports_must_match(tmp_path: Path) -> None:
    first = tmp_path / "project.toml"
    second = tmp_path / "global.toml"
    body = """
[mcp_servers.zai_web_search]
url = "https://example.invalid/search"
enabled_tools = ["web_search_prime"]
""".strip()
    first.write_text(body, encoding="utf-8")
    second.write_text(body, encoding="utf-8")
    reports = [
        check_mcp_config.inspect_config(check_mcp_config.load_config(first)),
        check_mcp_config.inspect_config(check_mcp_config.load_config(second)),
    ]
    assert check_mcp_config.compare_reports(reports) == []


def test_key_like_literal_is_rejected_without_printing_value(tmp_path: Path, capsys) -> None:
    config = tmp_path / "literal.toml"
    marker = "s" + "k-" + "fixture-not-a-real-key"
    config.write_text(
        """
[mcp_servers.zai_web_search]
url = "https://example.invalid/search"
enabled_tools = ["web_search_prime"]
""".strip()
        + f"\ncomment = {marker!r}\n",
        encoding="utf-8",
    )
    report = check_mcp_config.inspect_config(check_mcp_config.load_config(config))
    assert any("classified" in error for error in report["errors"])
    assert marker not in " ".join(report["errors"])
    assert check_mcp_config.main(["--config", str(config), "--json"]) == 1
    assert marker not in capsys.readouterr().out
