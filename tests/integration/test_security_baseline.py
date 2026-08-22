from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_security_baseline_contract_and_synthetic_suite_pass() -> None:
    contract = tomllib.loads((ROOT / "config" / "security-baseline.toml").read_text(encoding="utf-8"))
    assert contract["version"] == 2
    assert contract["name"] == "SECURITY_BASELINE"
    assert contract["synthetic_fixtures_only"] is True
    assert contract["dispatcher"] == ".codex/hooks/security_pre_tool_dispatch.py"

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gates" / "security-baseline.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["name"] == "SECURITY_BASELINE"
    assert report["version"] == 2
    assert report["passed"] is True
    assert all(item["passed"] for item in report["results"])
    assert "synthetic-baseline-value" not in result.stdout


def test_active_project_hook_registration_is_security_only() -> None:
    config = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    assert set(config["hooks"]) == {"PreToolUse"}
    entries = config["hooks"]["PreToolUse"]
    assert len(entries) == 1
    hooks = entries[0]["hooks"]
    assert len(hooks) == 1
    assert "security_pre_tool_dispatch.py" in hooks[0]["command"]
    assert "/.codex/hooks/pre_tool_dispatch.py" not in hooks[0]["command"]
