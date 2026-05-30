from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load_gate_script(monkeypatch: pytest.MonkeyPatch, filename: str) -> ModuleType:
    monkeypatch.syspath_prepend(str(ROOT / "scripts" / "gates"))
    path = ROOT / "scripts" / "gates" / filename
    module_name = f"test_{filename.replace('-', '_').replace('.', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_gate(*args: str, report_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GATES_REPORT_DIR"] = str(report_dir)
    env["RALPH_GATES_SKIP_TEST_EXECUTION"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gates" / "run-gates.py"), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_run_gates_minimal_generates_reports(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    result = run_gate("--minimal", report_dir=report_dir)
    assert result.returncode == 0, result.stderr

    latest_json = report_dir / "latest.json"
    latest_md = report_dir / "latest.md"
    assert latest_json.is_file()
    assert latest_md.is_file()

    report = json.loads(latest_json.read_text())
    markdown = latest_md.read_text()
    assert report["mode"] == "minimal"
    assert report["summary"]["status"] == "passed"
    assert report["results"]
    assert "# Quality Gates Report" in markdown
    assert "Mode: minimal" in markdown
    assert all(item["status"] in {"passed", "failed", "skipped"} for item in report["results"])

    stdout = json.loads(result.stdout)
    assert stdout["json"] == str(latest_json)
    assert stdout["markdown"] == str(latest_md)


def test_python_gate_disables_pytest_plugin_autoload(monkeypatch: pytest.MonkeyPatch) -> None:
    run_tests = load_gate_script(monkeypatch, "run-tests.py")
    calls: list[dict] = []

    def fake_run_command(
        name: str,
        command: list[str],
        timeout: int = 120,
        env: dict[str, str] | None = None,
    ) -> dict:
        calls.append({"name": name, "command": command, "timeout": timeout, "env": env})
        return {
            "name": name,
            "status": "passed",
            "command": command,
            "reason": "",
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
        }

    monkeypatch.setattr(run_tests, "run_command", fake_run_command)
    project = {
        "python": {"present": True, "tests_dir": True, "ruff": False, "mypy": False},
    }

    results = run_tests.python_results(project, "minimal")

    assert results[0]["status"] == "passed"
    assert calls == [
        {
            "name": "python.pytest",
            "command": ["python3", "-m", "pytest", "-q"],
            "timeout": 180,
            "env": {"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        }
    ]


def test_shell_file_detection_uses_git_tracked_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    gate_common = load_gate_script(monkeypatch, "_gate_common.py")
    local_env_script = tmp_path / ".venv-model-router" / "lib" / "completion.sh"
    local_env_script.parent.mkdir(parents=True)
    local_env_script.write_text("echo ignored\n", encoding="utf-8")

    def fake_run(
        command: list[str],
        cwd: Path,
        text: bool,
        capture_output: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert command == ["git", "ls-files", "*.sh"]
        assert cwd == tmp_path
        assert text is True
        assert capture_output is True
        assert check is False
        return subprocess.CompletedProcess(command, 0, stdout="scripts/setup/doctor.sh\n", stderr="")

    monkeypatch.setattr(gate_common.subprocess, "run", fake_run)

    assert gate_common.tracked_shell_files(tmp_path) == ["scripts/setup/doctor.sh"]


@pytest.mark.parametrize("mode", ["minimal", "standard", "full", "critical"])
def test_run_tests_modes_keep_expected_shape(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    run_tests = load_gate_script(monkeypatch, "run-tests.py")
    project = {
        "python": {"present": True, "tests_dir": True, "ruff": False, "mypy": False},
        "node": {"present": False},
        "shell": {"files": [], "shellcheck": False},
    }
    monkeypatch.setenv("RALPH_GATES_SKIP_TEST_EXECUTION", "1")

    results = (
        run_tests.python_results(project, mode)
        + run_tests.node_results(project, mode)
        + run_tests.shell_results(project, mode)
    )

    assert results
    assert all(item["status"] in {"passed", "failed", "skipped"} for item in results)
    assert any(item["name"] == "python.pytest" and item["status"] == "skipped" for item in results)


def test_detect_project_outputs_real_capabilities() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gates" / "detect-project.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["python"]["present"] is True
    assert "security" in data


def test_security_minimal_skips_without_failure() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gates" / "run-security.py"), "--mode", "minimal"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["results"][0]["status"] == "skipped"
