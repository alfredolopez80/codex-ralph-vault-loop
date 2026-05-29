from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"


def run_hook(name: str, ralph_home: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["RALPH_HOME"] = str(ralph_home)
    env["CODEX_MEMORY_HOME"] = str(ralph_home / "codex-memories-empty")
    env["RALPH_LOCAL_NOTES_ROOTS"] = ""
    return subprocess.run(
        [sys.executable, str(HOOKS / name)],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def long_alpha_payload() -> str:
    return "".join(["A"] * 4100)


def assert_blocked(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    return payload


def test_user_prompt_submit_blocks_inline_payload_without_echoing_it(tmp_path: Path) -> None:
    data_uri = "data:" + "image/png;" + "base64," + long_alpha_payload()
    result = run_hook("user_prompt_capture.py", tmp_path, {"hook_event_name": "UserPromptSubmit", "prompt": data_uri})

    payload = assert_blocked(result)
    assert "data:image" not in payload["reason"]
    assert long_alpha_payload() not in result.stdout


def test_user_prompt_submit_allows_normal_task_prompt(tmp_path: Path) -> None:
    result = run_hook(
        "user_prompt_capture.py",
        tmp_path,
        {"hook_event_name": "UserPromptSubmit", "session_id": "safe", "prompt": "Implement the scoped hook unit tests."},
    )

    assert result.returncode == 0, result.stderr
    if result.stdout.strip().startswith("{"):
        payload = json.loads(result.stdout)
        assert payload.get("decision") != "block"


def test_pre_tool_blocks_base64_encode_and_allows_decode(tmp_path: Path) -> None:
    blocked = run_hook("pre_tool_guard.py", tmp_path, {"tool_input": {"command": "base64 fixture.png", "cwd": str(tmp_path)}})
    chained = run_hook("pre_tool_guard.py", tmp_path, {"tool_input": {"command": "true && env SAMPLE=1 base64 fixture.png", "cwd": str(tmp_path)}})
    allowed = run_hook("pre_tool_guard.py", tmp_path, {"tool_input": {"command": "base64 --decode fixture.b64", "cwd": str(tmp_path)}})

    payload = assert_blocked(blocked)
    assert "base64" in payload["reason"]
    assert_blocked(chained)
    assert allowed.returncode == 0
    assert allowed.stdout == ""


def test_pre_tool_blocks_huge_and_binary_file_dumps_with_guidance(tmp_path: Path) -> None:
    huge = tmp_path / "huge.json"
    huge.write_text("x" * 70000, encoding="utf-8")
    image = tmp_path / "image.png"
    image.write_bytes(b"fake")

    huge_result = run_hook("pre_tool_guard.py", tmp_path, {"tool_input": {"command": f"cat {huge}", "cwd": str(tmp_path)}})
    image_result = run_hook("pre_tool_guard.py", tmp_path, {"tool_input": {"command": f"cat {image}", "cwd": str(tmp_path)}})

    huge_payload = assert_blocked(huge_result)
    image_payload = assert_blocked(image_result)
    assert "suggested_command" in huge_payload
    assert "binary" in image_payload["reason"]


def test_pre_tool_allows_small_text_and_targeted_rg(tmp_path: Path) -> None:
    small = tmp_path / "small.txt"
    small.write_text("safe\n", encoding="utf-8")
    for command in [f"cat {small}", "rg -n context docs .codex/hooks"]:
        result = run_hook("pre_tool_guard.py", tmp_path, {"tool_input": {"command": command, "cwd": str(ROOT)}})
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""


def test_pre_tool_blocks_broad_rg_over_high_risk_root(tmp_path: Path) -> None:
    result = run_hook("pre_tool_guard.py", tmp_path, {"tool_input": {"command": "rg -n context ~/.codex", "cwd": str(ROOT)}})

    payload = assert_blocked(result)
    assert "high-risk" in payload["reason"]
    assert "suggested_command" in payload


def test_pre_tool_blocks_toxic_patch_but_not_normal_patch_text(tmp_path: Path) -> None:
    toxic_patch = {"tool_input": {"patch": "*** Begin Patch\n+" + long_alpha_payload() + "\n*** End Patch"}}
    normal_patch = {"tool_input": "*** Begin Patch\n*** Add File: example.txt\n+hello\n*** End Patch"}

    blocked = run_hook("pre_tool_guard.py", tmp_path, toxic_patch)
    allowed = run_hook("pre_tool_guard.py", tmp_path, normal_patch)

    assert_blocked(blocked)
    assert allowed.returncode == 0
    assert allowed.stdout == ""
