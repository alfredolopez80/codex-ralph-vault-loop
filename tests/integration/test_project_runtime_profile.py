from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_project_runtime_profile_uses_luna_max_with_bounded_multi_agent() -> None:
    config = tomllib.loads((ROOT / ".codex" / "config.toml").read_text(encoding="utf-8"))

    assert config["model"] == "gpt-5.6-luna"
    assert config["model_reasoning_effort"] == "max"
    assert config["features"]["multi_agent"] is True
    assert config["features"]["hooks"] is True
    assert "codex_hooks" not in config["features"]
    assert config["agents"]["max_threads"] == 4
    assert config["agents"]["max_depth"] == 1
