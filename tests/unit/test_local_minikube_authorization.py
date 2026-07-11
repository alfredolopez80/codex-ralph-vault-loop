from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
sys.path.insert(0, str(HOOKS))

from shared.local_minikube_grant import allows, digest, targets  # noqa: E402


def write_grant(grant_root: Path, patch: str, target: Path, *, expired: bool = False) -> None:
    grant_root.mkdir(mode=0o700, exist_ok=True)
    path = grant_root / f"{digest(patch)}.approved"
    path.write_text("", encoding="utf-8")
    path.chmod(0o600)
    if expired:
        old = path.stat().st_mtime - 901
        os.utime(path, (old, old))


def test_grant_requires_exact_patch_target_and_unexpired_hash(tmp_path: Path, monkeypatch) -> None:
    notes = tmp_path / ".local-notes"
    notes.mkdir()
    target = notes / "seed.sh"
    marker = "PASS" + "WORD"
    patch = f"*** Begin Patch\n*** Add File: .local-notes/seed.sh\n+{marker}=generated\n*** End Patch"
    grant_root = tmp_path / "grants"
    monkeypatch.setenv("CODEX_LOCAL_GRANT_ROOT", str(grant_root))
    write_grant(grant_root, patch, target)

    assert allows(patch, tmp_path)
    assert not allows(patch + "\n", tmp_path)
    assert targets(patch.replace(".local-notes", "scripts"), tmp_path) is None


def test_grant_rejects_expired_or_group_readable_file(tmp_path: Path, monkeypatch) -> None:
    notes = tmp_path / ".local-notes"
    notes.mkdir()
    target = notes / "seed.sh"
    patch = "*** Begin Patch\n*** Add File: .local-notes/seed.sh\n+hello\n*** End Patch"
    grant_root = tmp_path / "grants"
    monkeypatch.setenv("CODEX_LOCAL_GRANT_ROOT", str(grant_root))
    write_grant(grant_root, patch, target, expired=True)
    assert not allows(patch, tmp_path)

    write_grant(grant_root, patch, target)
    (grant_root / f"{digest(patch)}.approved").chmod(0o640)
    assert not allows(patch, tmp_path)


def test_grant_rejects_tracked_local_notes_target(tmp_path: Path) -> None:
    notes = tmp_path / ".local-notes"
    notes.mkdir()
    target = notes / "seed.sh"
    target.write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "add", str(target)], cwd=tmp_path, capture_output=True, check=True)
    patch = "*** Begin Patch\n*** Update File: .local-notes/seed.sh\n+hello\n*** End Patch"
    assert targets(patch, tmp_path) is None

def test_pre_tool_guard_uses_exact_local_grant(tmp_path: Path) -> None:
    notes = tmp_path / ".local-notes"
    notes.mkdir()
    target = notes / "seed.sh"
    marker = "PASS" + "WORD"
    patch = f"*** Begin Patch\n*** Add File: .local-notes/seed.sh\n+{marker}=generated\n*** End Patch"
    grant_root = tmp_path / "grants"
    write_grant(grant_root, patch, target)
    env = os.environ.copy()
    env["CODEX_LOCAL_GRANT_ROOT"] = str(grant_root)
    result = subprocess.run(
        [sys.executable, str(HOOKS / "pre_tool_guard.py")],
        input=json.dumps({"tool_input": {"patch": patch, "cwd": str(tmp_path)}}),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == ""


def test_pre_tool_guard_returns_actionable_request_when_grant_is_missing(tmp_path: Path) -> None:
    notes = tmp_path / ".local-notes"
    notes.mkdir()
    marker = "PASS" + "WORD"
    patch = f"*** Begin Patch\n*** Add File: .local-notes/seed.sh\n+{marker}=generated\n*** End Patch"
    grant_root = tmp_path / "grants"
    env = os.environ.copy()
    env["CODEX_LOCAL_GRANT_ROOT"] = str(grant_root)
    result = subprocess.run(
        [sys.executable, str(HOOKS / "pre_tool_guard.py")],
        input=json.dumps({"tool_input": {"patch": patch, "cwd": str(tmp_path)}}),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert payload["reason_code"] == "local_patch_grant_required"
    assert payload["patch_sha256"] == digest(patch)
    assert payload["targets"] == [str(notes / "seed.sh")]
    assert "authorize-local-minikube-patch" in payload["suggested_command"]
    assert digest(patch) in payload["suggested_command"]


def load_runner():
    path = ROOT / "scripts" / "security" / "run-local-minikube-script.py"
    spec = importlib.util.spec_from_file_location("run_local_minikube_script", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runner_rejects_endpoint_mismatch(tmp_path: Path, monkeypatch) -> None:
    notes = tmp_path / ".local-notes"
    notes.mkdir()
    script = notes / "seed.sh"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o700)
    runner = load_runner()
    outputs = iter(
        [
            json.dumps({"Host": "Running", "APIServer": "Running"}),
            "minikube-profile",
            "https://production.example",
            "https://127.0.0.1:8443",
        ]
    )
    monkeypatch.setattr(runner, "checked_output", lambda *args: next(outputs))
    monkeypatch.setattr(sys, "argv", ["runner", "--profile", "profile", "--context", "minikube-profile", str(script)])
    try:
        runner.main()
    except SystemExit as exc:
        assert "does not belong" in str(exc)
    else:
        raise AssertionError("endpoint mismatch must be refused")
