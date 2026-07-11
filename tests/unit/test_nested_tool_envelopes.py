from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".codex" / "hooks" / "pre_tool_guard.py"


def run_guard(tmp_path: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CODEX_LOCAL_GRANT_ROOT"] = str(tmp_path / "approvals")
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def local_patch() -> str:
    return "*** Begin Patch\n*** Add File: .local-notes/seed.sh\n+hello\n*** End Patch"


def test_native_and_safe_nested_local_patches_are_allowed(tmp_path: Path) -> None:
    (tmp_path / ".local-notes").mkdir()
    patch = local_patch()
    literal = json.dumps(patch)
    sources = [
        f"text(await tools.apply_patch({literal}));",
        f"const patch = {literal}; text(await tools.apply_patch(patch));",
        f"const patch = {literal}; const result = await tools.apply_patch(patch); text(result);",
        f"text(await tools.apply_patch(`{patch}`));",
    ]
    native = run_guard(tmp_path, {"tool_input": {"patch": patch, "cwd": str(tmp_path)}})
    assert native.stdout == ""
    for source in sources:
        result = run_guard(tmp_path, {"tool_input": {"source": source, "cwd": str(tmp_path)}})
        assert result.returncode == 0, result.stderr
        assert result.stdout == "", source
    for field in ("code", "script"):
        result = run_guard(tmp_path, {"tool_input": {field: sources[1], "cwd": str(tmp_path)}})
        assert result.stdout == ""


def test_dynamic_nested_patch_envelopes_are_rejected(tmp_path: Path) -> None:
    (tmp_path / ".local-notes").mkdir()
    patch = local_patch()
    literal = json.dumps(patch)
    unsafe_sources = [
        "const patch = getPatch(); text(await tools.apply_patch(patch));",
        f"const patch = {literal} + suffix; text(await tools.apply_patch(patch));",
        "text(await tools.apply_patch(`*** Begin Patch\\n${body}\\n*** End Patch`));",
        f"text(await tools.apply_patch({literal})); text(await tools.apply_patch({literal}));",
    ]
    for source in unsafe_sources:
        result = run_guard(tmp_path, {"tool_input": {"source": source, "cwd": str(tmp_path)}})
        payload = json.loads(result.stdout)
        assert payload["reason_code"] == "unsafe_nested_patch_envelope", source


def test_effectful_nested_patch_envelopes_are_rejected(tmp_path: Path) -> None:
    (tmp_path / ".local-notes").mkdir()
    literal = json.dumps(local_patch())
    extra = "await tools.exec_command({cmd: \"kubectl get pods\"});"
    sources = [
        f"text(await tools.apply_patch({literal})); {extra}",
        f"{extra} text(await tools.apply_patch({literal}));",
    ]
    for source in sources:
        result = run_guard(tmp_path, {"tool_input": {"source": source, "cwd": str(tmp_path)}})
        payload = json.loads(result.stdout)
        assert payload["reason_code"] == "unsafe_nested_patch_envelope"


def test_nested_exec_command_uses_same_cloud_gate(tmp_path: Path) -> None:
    command = "kubectl delete namespace feature-test"
    source = f"const result = await tools.exec_command({{cmd: {json.dumps(command)}}}); text(result.output);"
    result = run_guard(tmp_path, {"tool_input": {"source": source, "cwd": str(tmp_path)}})
    payload = json.loads(result.stdout)
    assert payload["reason_code"] == "cloud_command_approval_required"
    assert payload["risk_level"] == "destructive"


def test_nested_exec_rejects_multiple_tool_calls(tmp_path: Path) -> None:
    call = "await tools.exec_command({cmd: \"kubectl get pods\"});"
    result = run_guard(tmp_path, {"tool_input": {"source": call + call, "cwd": str(tmp_path)}})
    payload = json.loads(result.stdout)
    assert payload["reason_code"] == "unsafe_nested_command_envelope"
