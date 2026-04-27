#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os

from _gate_common import detect_project, result, run_command


def python_results(project: dict, mode: str) -> list[dict]:
    py = project["python"]
    results = []
    if not py["present"]:
        return [result("python.pytest", "skipped", reason="no Python project detected")]
    if os.environ.get("RALPH_GATES_SKIP_TEST_EXECUTION") == "1":
        return [result("python.pytest", "skipped", reason="test execution disabled by environment")]
    if py["tests_dir"]:
        results.append(run_command("python.pytest", ["python3", "-m", "pytest", "-q"], timeout=180))
    else:
        results.append(result("python.pytest", "skipped", reason="tests directory missing"))
    if mode in {"standard", "full", "critical"}:
        if py["ruff"]:
            results.append(run_command("python.ruff", ["ruff", "check", "."], timeout=120))
        else:
            results.append(result("python.ruff", "skipped", reason="ruff not installed"))
    if mode in {"full", "critical"}:
        if py["mypy"]:
            results.append(run_command("python.mypy", ["mypy", "."], timeout=180))
        else:
            results.append(result("python.mypy", "skipped", reason="mypy not installed"))
    return results


def node_results(project: dict, mode: str) -> list[dict]:
    node = project["node"]
    if not node["present"]:
        return [result("node", "skipped", reason="no package.json detected")]
    manager = node["package_manager"]
    if not manager or not node.get(manager):
        return [result("node", "skipped", reason="package manager not available")]
    scripts = node["scripts"]
    results = []
    script_names = ["test"] if mode == "minimal" else ["test", "lint", "typecheck"]
    for script in script_names:
        if script in scripts:
            results.append(run_command(f"node.{script}", [manager, "run", script], timeout=180))
        else:
            results.append(result(f"node.{script}", "skipped", reason=f"script {script} not defined"))
    return results


def shell_results(project: dict, mode: str) -> list[dict]:
    shell = project["shell"]
    if mode not in {"full", "critical"}:
        return []
    if not shell["files"]:
        return [result("shell.shellcheck", "skipped", reason="no shell files detected")]
    if not shell["shellcheck"]:
        return [result("shell.shellcheck", "skipped", reason="shellcheck not installed")]
    return [run_command("shell.shellcheck", ["shellcheck", *shell["files"]], timeout=120)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run project test, lint, and typecheck gates.")
    parser.add_argument("--mode", choices=["minimal", "standard", "full", "critical"], default="standard")
    args = parser.parse_args()

    project = detect_project()
    results = python_results(project, args.mode) + node_results(project, args.mode) + shell_results(project, args.mode)
    print(json.dumps({"results": results}, indent=2, sort_keys=True))
    return 1 if any(item["status"] == "failed" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
