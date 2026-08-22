from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECURITY_DISPATCHER = ROOT / ".codex" / "hooks" / "security_pre_tool_dispatch.py"


def run_security_dispatcher(tmp_path: Path, command: str, grant_root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CODEX_LOCAL_GRANT_ROOT"] = str(grant_root)
    return subprocess.run(
        [sys.executable, str(SECURITY_DISPATCHER)],
        cwd=tmp_path,
        env=env,
        input=json.dumps(
            {
                "tool_name": "exec_command",
                "cwd": str(tmp_path),
                "tool_input": {"cmd": command, "workdir": str(tmp_path)},
            }
        ),
        text=True,
        capture_output=True,
        check=False,
    )


def run_security_dispatcher_raw(tmp_path: Path, raw: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SECURITY_DISPATCHER)],
        cwd=tmp_path,
        input=raw,
        text=True,
        capture_output=True,
        check=False,
    )


def test_security_baseline_contract_and_synthetic_suite_pass() -> None:
    contract = tomllib.loads((ROOT / "config" / "security-baseline.toml").read_text(encoding="utf-8"))
    assert contract["version"] == 3
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
    assert report["version"] == 3
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


def test_security_only_approval_is_visible_exact_and_one_use(tmp_path: Path) -> None:
    command = "aws s3 cp artifact s3://example-bucket/artifact"
    grant_root = tmp_path / "approvals"

    first = run_security_dispatcher(tmp_path, command, grant_root)

    assert first.returncode == 0, first.stderr
    payload = json.loads(first.stdout)
    assert set(payload) == {"decision", "reason"}
    assert payload["decision"] == "block"
    match = re.search(r"approve-risky-command --sha256 ([0-9a-f]{64})", payload["reason"])
    assert match, payload["reason"]
    assert "Risk: aws/mutating" in payload["reason"]
    assert "consequence: cp cluster or cloud state" in payload["reason"]

    grant_root.mkdir(mode=0o700)
    marker = grant_root / f"command-{match.group(1)}.approved"
    marker.write_text("", encoding="utf-8")
    marker.chmod(0o600)

    second = run_security_dispatcher(tmp_path, command, grant_root)
    assert second.returncode == 0, second.stderr
    assert second.stdout == ""
    assert not marker.exists()

    third = run_security_dispatcher(tmp_path, command, grant_root)
    assert json.loads(third.stdout)["decision"] == "block"


def test_security_dispatcher_blocks_malformed_or_non_object_input(tmp_path: Path) -> None:
    for raw in ("{invalid-json", '"not-an-object"'):
        result = run_security_dispatcher_raw(tmp_path, raw)

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert set(payload) == {"decision", "reason"}
        assert payload["decision"] == "block"
        assert "retry" in payload["reason"].lower()


def test_security_dispatcher_blocks_oversized_input(tmp_path: Path) -> None:
    raw = json.dumps({"tool_name": "exec_command", "padding": "x" * (4 * 1024 * 1024)})

    result = run_security_dispatcher_raw(tmp_path, raw)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert set(payload) == {"decision", "reason"}
    assert payload["decision"] == "block"
    assert "oversized" in payload["reason"].lower()
