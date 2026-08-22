#!/usr/bin/env python3
"""Run the versioned synthetic SECURITY_BASELINE fixture suite."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "security-baseline.toml"
DISPATCHER = ROOT / ".codex" / "hooks" / "security_pre_tool_dispatch.py"


def load_contract() -> dict[str, Any]:
    with CONFIG.open("rb") as stream:
        contract = tomllib.load(stream)
    if contract.get("version") != 2 or contract.get("name") != "SECURITY_BASELINE":
        raise RuntimeError("SECURITY_BASELINE contract version or name is invalid")
    if contract.get("dispatcher") != ".codex/hooks/security_pre_tool_dispatch.py":
        raise RuntimeError("SECURITY_BASELINE dispatcher does not identify the security-only hook")
    return contract


def run_hook(payload: dict[str, Any], runtime: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env.update(
        {
            "RALPH_HOME": str(runtime / "ralph"),
            "CODEX_MEMORY_HOME": str(runtime / "empty-memory"),
            "RALPH_LOCAL_NOTES_ROOTS": "",
            "CODEX_HOOK_STATE_ROOT": str(runtime / "hook-state"),
        }
    )
    result = subprocess.run(
        [sys.executable, str(DISPATCHER)],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        return {"blocked": False, "error": "dispatcher returned non-zero"}
    output = result.stdout.strip()
    if not output:
        return {"blocked": False, "reason_code": None}
    try:
        decoded = json.loads(output)
    except json.JSONDecodeError:
        return {"blocked": False, "error": "dispatcher emitted invalid JSON"}
    if not isinstance(decoded, dict):
        return {"blocked": False, "error": "dispatcher emitted a non-object JSON value"}
    return {
        "blocked": decoded.get("decision") == "block",
        "reason_code": decoded.get("reason_code"),
    }


def case(name: str, payload: dict[str, Any], expected_blocked: bool) -> dict[str, Any]:
    return {"name": name, "payload": payload, "expected_blocked": expected_blocked}


def run_cases(runtime: Path) -> list[dict[str, Any]]:
    workspace = runtime / "workspace"
    workspace.mkdir()
    outside = runtime / "outside"
    outside.mkdir()
    escape = workspace / "escape"
    escape.symlink_to(outside, target_is_directory=True)
    synthetic_key_name = "API" + "_KEY"
    harmless_script = workspace / "fixture_check.py"
    harmless_script.write_text(
        'fixture = "aws ec2 terminate-instances --instance-ids i-synthetic"\nprint("fixture only")\n',
        encoding="utf-8",
    )
    harmless_shell_syntax = workspace / "cloud_syntax_fixture.sh"
    harmless_shell_syntax.write_text(
        "#!/bin/sh\nif false; then\n  aws s3 cp fixture s3://synthetic-bucket/fixture\nfi\n",
        encoding="utf-8",
    )

    cases = [
        case(
            "destructive-command",
            {"tool_name": "exec_command", "cwd": str(workspace), "tool_input": {"cmd": "git reset --hard HEAD"}},
            True,
        ),
        case(
            "write-outside-workspace",
            {"tool_name": "apply_patch", "cwd": str(workspace), "tool_input": {"path": str(outside / "file.txt")}},
            True,
        ),
        case(
            "symlink-path-escape",
            {"tool_name": "apply_patch", "cwd": str(workspace), "tool_input": {"path": "escape/file.txt"}},
            True,
        ),
        case(
            "synthetic-sensitive-mcp-egress",
            {
                "tool_name": "mcp__synthetic__send",
                "cwd": str(workspace),
                "tool_input": {"body": f"{synthetic_key_name}=synthetic-baseline-value"},
            },
            True,
        ),
        case(
            "package-manager-network",
            {"tool_name": "exec_command", "cwd": str(workspace), "tool_input": {"cmd": "npm install synthetic-package"}},
            True,
        ),
        case(
            "cloud-destructive-approval",
            {
                "tool_name": "exec_command",
                "cwd": str(workspace),
                "tool_input": {"cmd": "aws ec2 terminate-instances --instance-ids i-synthetic"},
            },
            True,
        ),
        case(
            "nested-cloud-destructive-approval",
            {
                "tool_name": "exec_command",
                "cwd": str(workspace),
                "tool_input": {"cmd": "bash -c 'aws ec2 terminate-instances --instance-ids i-synthetic'"},
            },
            True,
        ),
        case(
            "harmless-read",
            {"tool_name": "exec_command", "cwd": str(workspace), "tool_input": {"cmd": "git status"}},
            False,
        ),
        case(
            "harmless-scoped-tool-read",
            {
                "tool_name": "exec_command",
                "cwd": str(workspace),
                "tool_input": {"cmd": "ls -l node_modules/.bin/prettier"},
            },
            False,
        ),
        case(
            "harmless-scoped-search",
            {
                "tool_name": "exec_command",
                "cwd": str(workspace),
                "tool_input": {"cmd": "rg -n prettier .pre-commit-config.yaml package.json"},
            },
            False,
        ),
        case(
            "harmless-local-script-with-cloud-fixture-text",
            {
                "tool_name": "exec_command",
                "cwd": str(workspace),
                "tool_input": {"cmd": f"{sys.executable} {harmless_script}"},
            },
            False,
        ),
        case(
            "harmless-shell-noexec-validation",
            {
                "tool_name": "exec_command",
                "cwd": str(workspace),
                "tool_input": {"cmd": f"bash -n {harmless_shell_syntax}"},
            },
            False,
        ),
        case(
            "harmless-workspace-write-target",
            {"tool_name": "apply_patch", "cwd": str(workspace), "tool_input": {"path": str(workspace / "safe.txt")}},
            False,
        ),
        case(
            "harmless-external-input",
            {"tool_name": "mcp__synthetic__send", "cwd": str(workspace), "tool_input": {"body": "fixture hello"}},
            False,
        ),
        case(
            "native-generic-subagent",
            {
                "tool_name": "spawn_agent",
                "cwd": str(workspace),
                "tool_input": {"agent_type": "default", "message": "read-only synthetic fixture"},
            },
            False,
        ),
    ]

    results: list[dict[str, Any]] = []
    for item in cases:
        observed = run_hook(item["payload"], runtime)
        passed = "error" not in observed and observed["blocked"] == item["expected_blocked"]
        results.append(
            {
                "name": item["name"],
                "expected": "blocked" if item["expected_blocked"] else "allowed",
                "observed": "blocked" if observed["blocked"] else "allowed",
                "reason_code": observed.get("reason_code"),
                "passed": passed,
                **({"error": observed["error"]} if "error" in observed else {}),
            }
        )
    return results


def main() -> int:
    contract = load_contract()
    with tempfile.TemporaryDirectory(prefix="security-baseline-") as temp:
        results = run_cases(Path(temp).resolve())
    report = {
        "name": contract["name"],
        "version": contract["version"],
        "dispatcher": contract["dispatcher"],
        "synthetic_only": contract["synthetic_fixtures_only"],
        "passed": all(item["passed"] for item in results),
        "results": results,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
