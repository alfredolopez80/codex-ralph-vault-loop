#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


GLOBAL_HOOK_DIR = Path.home() / ".codex" / "hooks"
GLOBAL_HOOKS_JSON = Path.home() / ".codex" / "hooks.json"


def run_hook(name: str, payload: dict, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GLOBAL_HOOK_DIR / name)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=os.environ.copy() | env,
        check=False,
    )


def assert_ok(label: str, result: subprocess.CompletedProcess[str]) -> None:
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed: {result.stderr or result.stdout}")


def hook_basenames(config: dict, event: str) -> list[str]:
    names: list[str] = []
    for group in config.get("hooks", {}).get(event, []):
        for hook in group.get("hooks", []):
            matches = re.findall(r"([A-Za-z0-9_.-]+\.(?:py|sh))", str(hook.get("command", "")))
            if matches:
                names.append(matches[-1])
    return names


def main() -> int:
    if not GLOBAL_HOOKS_JSON.is_file():
        print(f"GLOBAL_HOOKS_SMOKE_FAIL missing {GLOBAL_HOOKS_JSON}", file=sys.stderr)
        return 1
    config = json.loads(GLOBAL_HOOKS_JSON.read_text(encoding="utf-8"))
    required = {
        "SessionStart": ["session_start_wakeup.py"],
        "UserPromptSubmit": ["user_prompt_capture.py", "continuity_prompt_context.py"],
        "PostToolUse": ["post_tool_extract_memory.py", "post_tool_checkpoint.py", "post_tool_cost_ledger.py"],
        "Stop": ["stop_persist_memory.py", "stop_memory_promotion_review.py"],
    }
    for event, names in required.items():
        sequence = hook_basenames(config, event)
        missing = [name for name in names if name not in sequence]
        if missing:
            print(f"GLOBAL_HOOKS_SMOKE_FAIL missing {event} hooks {missing}", file=sys.stderr)
            return 1
    repo_root_file = GLOBAL_HOOK_DIR / ".ralph-repo-root"
    if not repo_root_file.is_file():
        print(f"GLOBAL_HOOKS_SMOKE_FAIL missing {repo_root_file}", file=sys.stderr)
        return 1
    repo_root = Path(repo_root_file.read_text(encoding="utf-8").strip())
    if not (repo_root / "scripts" / "memory" / "wakeup.py").is_file():
        print(f"GLOBAL_HOOKS_SMOKE_FAIL invalid repo root {repo_root}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        env = {
            "RALPH_HOME": str(base / "ralph"),
            "CODEX_MEMORY_HOME": str(base / "empty-codex-memory"),
            "RALPH_LOCAL_NOTES_ROOTS": "",
            "CODEX_SESSION_ID": "global-hook-smoke",
            "VAULT_PROJECT": "codex-ralph-vault-loop",
        }
        prompt = run_hook(
            "continuity_prompt_context.py",
            {"session_id": "global-hook-smoke", "prompt": "Implement global hook smoke validation."},
            env,
        )
        assert_ok("continuity_prompt_context.py", prompt)
        checkpoint_path = Path(env["RALPH_HOME"]) / "checkpoints" / "latest.json"
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint["objective"] != "Implement global hook smoke validation.":
            raise RuntimeError("prompt checkpoint objective mismatch")

        post_tool = run_hook(
            "post_tool_checkpoint.py",
            {"tool_input": {"command": "python3 -m pytest tests/integration/test_hook_lifecycle_e2e.py"}, "success": True},
            env,
        )
        assert_ok("post_tool_checkpoint.py", post_tool)
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint["validation_status"] != "pass":
            raise RuntimeError("post tool checkpoint did not mark validation pass")

        wakeup = run_hook("session_start_wakeup.py", {}, env)
        assert_ok("session_start_wakeup.py", wakeup)
        if "Latest Rolling Checkpoint" not in wakeup.stdout:
            raise RuntimeError("session start did not include rolling checkpoint")

        stop = run_hook("stop_persist_memory.py", {"last_assistant_message": "Global hook smoke finished."}, env)
        assert_ok("stop_persist_memory.py", stop)
        handoff = (Path(env["RALPH_HOME"]) / "handoffs" / "latest.md").read_text(encoding="utf-8")
        if "## Rolling Checkpoint" not in handoff:
            raise RuntimeError("stop handoff missing rolling checkpoint")

    print(f"GLOBAL_HOOKS_SMOKE_PASS repo={repo_root}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"GLOBAL_HOOKS_SMOKE_FAIL {exc}", file=sys.stderr)
        raise SystemExit(1)
