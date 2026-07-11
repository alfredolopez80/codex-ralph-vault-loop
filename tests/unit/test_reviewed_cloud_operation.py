from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load_runner():
    path = ROOT / "scripts" / "operations" / "reviewed-cloud-operation.py"
    spec = importlib.util.spec_from_file_location("reviewed_cloud_operation", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_script(tmp_path: Path, *, dry_run_exit: int = 0) -> tuple[Path, Path]:
    notes = tmp_path / ".local-notes"
    notes.mkdir()
    log = tmp_path / "execution.log"
    script = notes / "operation.sh"
    script.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = "--dry-run" ]; then exit {dry_run_exit}; fi\n'
        f'printf "%s\\n" "$*" >> "{log}"\n',
        encoding="utf-8",
    )
    script.chmod(0o700)
    return script, log


def invoke(runner, monkeypatch, mode: str, script: Path, target: str, *args: str) -> int:
    monkeypatch.setattr(
        sys,
        "argv",
        ["runner", mode, "--script", str(script), "--target", target, *args],
    )
    return runner.main()


def test_requires_successful_dry_run_before_execution(tmp_path: Path, monkeypatch) -> None:
    runner = load_runner()
    script, log = make_script(tmp_path)
    monkeypatch.setenv("CODEX_REVIEWED_OPERATION_ROOT", str(tmp_path / "state"))

    with pytest.raises(SystemExit, match="dry-run is required"):
        invoke(runner, monkeypatch, "execute", script, "gcp/project-a/cluster-a", "apply")
    assert invoke(runner, monkeypatch, "dry-run", script, "gcp/project-a/cluster-a", "apply") == 0
    assert invoke(runner, monkeypatch, "execute", script, "gcp/project-a/cluster-a", "apply") == 0
    assert log.read_text(encoding="utf-8") == "apply\n"
    with pytest.raises(SystemExit, match="dry-run is required"):
        invoke(runner, monkeypatch, "execute", script, "gcp/project-a/cluster-a", "apply")


def test_changed_target_arguments_or_script_require_new_dry_run(tmp_path: Path, monkeypatch) -> None:
    runner = load_runner()
    script, _ = make_script(tmp_path)
    monkeypatch.setenv("CODEX_REVIEWED_OPERATION_ROOT", str(tmp_path / "state"))
    assert invoke(runner, monkeypatch, "dry-run", script, "aws/account-a/cluster-a", "apply") == 0

    with pytest.raises(SystemExit, match="dry-run is required"):
        invoke(runner, monkeypatch, "execute", script, "aws/account-b/cluster-a", "apply")
    with pytest.raises(SystemExit, match="dry-run is required"):
        invoke(runner, monkeypatch, "execute", script, "aws/account-a/cluster-a", "delete")
    script.write_text(script.read_text(encoding="utf-8") + "# reviewed change\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="dry-run is required"):
        invoke(runner, monkeypatch, "execute", script, "aws/account-a/cluster-a", "apply")


def test_failed_dry_run_does_not_create_evidence(tmp_path: Path, monkeypatch) -> None:
    runner = load_runner()
    script, _ = make_script(tmp_path, dry_run_exit=7)
    monkeypatch.setenv("CODEX_REVIEWED_OPERATION_ROOT", str(tmp_path / "state"))
    with pytest.raises(SystemExit, match="DRY_RUN_FAILED"):
        invoke(runner, monkeypatch, "dry-run", script, "gcp/project-a/cluster-a", "apply")
    with pytest.raises(SystemExit, match="dry-run is required"):
        invoke(runner, monkeypatch, "execute", script, "gcp/project-a/cluster-a", "apply")
