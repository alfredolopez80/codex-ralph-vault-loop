from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from collections import deque
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = Path(os.environ.get("GATES_REPORT_DIR", ".ralph-codex/reports/gates"))
MODES = {"minimal", "standard", "full", "critical"}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def repo_shell_files(root: Path = REPO_ROOT) -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.sh"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode == 0:
        return sorted(line for line in completed.stdout.splitlines() if line)
    return sorted(
        str(path.relative_to(root))
        for path in root.rglob("*.sh")
        if not {".git", ".ralph-codex", ".venv", ".venv-model-router", "node_modules", "__pycache__"}.intersection(path.parts)
    )


def detect_project(root: Path = REPO_ROOT) -> dict[str, Any]:
    package_json = root / "package.json"
    package_scripts: dict[str, str] = {}
    if package_json.exists():
        try:
            package_scripts = json.loads(package_json.read_text(encoding="utf-8")).get("scripts", {})
        except json.JSONDecodeError:
            package_scripts = {}

    return {
        "root": str(root),
        "python": {
            "present": (root / "pyproject.toml").exists() or (root / "tests").exists(),
            "pytest": command_exists("pytest") or command_exists("python3"),
            "ruff": command_exists("ruff"),
            "mypy": command_exists("mypy"),
            "tests_dir": (root / "tests").exists(),
        },
        "node": {
            "present": package_json.exists(),
            "scripts": package_scripts,
            "npm": command_exists("npm"),
            "pnpm": command_exists("pnpm"),
            "yarn": command_exists("yarn"),
            "package_manager": package_manager(root),
        },
        "shell": {
            "files": repo_shell_files(root),
            "shellcheck": command_exists("shellcheck"),
        },
        "security": {
            "gitleaks": command_exists("gitleaks"),
            "semgrep": command_exists("semgrep"),
        },
    }


def package_manager(root: Path) -> str | None:
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    if (root / "package-lock.json").exists() or (root / "package.json").exists():
        return "npm"
    return None


def result(name: str, status: str, command: list[str] | None = None, reason: str = "", stdout: str = "", stderr: str = "", exit_code: int | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "command": command,
        "reason": reason,
        "stdout": stdout[-4_000:],
        "stderr": stderr[-4_000:],
        "exit_code": exit_code,
    }


def run_command(
    name: str,
    command: list[str],
    timeout: int = 120,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    command_env = None
    if env is not None:
        command_env = os.environ.copy()
        command_env.update(env)
    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        env=command_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )
    stdout_tail: deque[str] = deque(maxlen=200)
    stderr_tail: deque[str] = deque(maxlen=200)

    def relay(stream: Any, target: deque[str]) -> None:
        if stream is None:
            return
        for line in iter(stream.readline, ""):
            target.append(line)
            print(line, end="", file=sys.stderr, flush=True)
        stream.close()

    readers = [
        threading.Thread(target=relay, args=(process.stdout, stdout_tail), daemon=True),
        threading.Thread(target=relay, args=(process.stderr, stderr_tail), daemon=True),
    ]
    for reader in readers:
        reader.start()
    timed_out = False
    try:
        return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        return_code = process.wait()
    for reader in readers:
        reader.join(timeout=5)

    status = "passed" if return_code == 0 and not timed_out else "failed"
    return result(
        name,
        status,
        command,
        reason=f"command timed out after {timeout}s" if timed_out else "",
        stdout="".join(stdout_tail),
        stderr="".join(stderr_tail),
        exit_code=return_code,
    )


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        "passed": sum(1 for item in results if item["status"] == "passed"),
        "failed": sum(1 for item in results if item["status"] == "failed"),
        "skipped": sum(1 for item in results if item["status"] == "skipped"),
    }
    counts["status"] = "failed" if counts["failed"] else "passed"
    return counts


def write_reports(report: dict[str, Any], report_dir: Path = REPORT_DIR) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "latest.json"
    md_path = report_dir / "latest.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Quality Gates Report",
        "",
        f"Created: {report.get('created_at', '')}",
        f"Mode: {report.get('mode', '')}",
        f"Status: {report.get('summary', {}).get('status', 'unknown')}",
        "",
        "## Results",
        "",
    ]
    for item in report.get("results", []):
        command = " ".join(item["command"]) if item.get("command") else "not run"
        reason = f" - {item['reason']}" if item.get("reason") else ""
        lines.append(f"- {item['status'].upper()} `{item['name']}`: `{command}`{reason}")
    lines.append("")
    return "\n".join(lines)
