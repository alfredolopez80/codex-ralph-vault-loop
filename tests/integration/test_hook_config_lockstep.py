from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "setup" / "install-global-hooks.py"


def hook_pairs(config: dict, event: str) -> list[tuple[str, int]]:
    pairs: list[tuple[str, int]] = []
    for group in config["hooks"].get(event, []):
        for hook in group.get("hooks", []):
            command = str(hook.get("command", ""))
            matches = re.findall(r"([A-Za-z0-9_.-]+\.(?:py|sh))", command)
            pairs.append((matches[-1] if matches else command, int(hook.get("timeout", 0))))
    return pairs


def generated_global_config(home: Path) -> dict:
    env = os.environ.copy()
    env["HOME"] = str(home)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    json_start = result.stdout.find("{")
    assert json_start >= 0, result.stdout
    return json.loads(result.stdout[json_start:])


def test_local_and_global_hook_configs_stay_in_lockstep(tmp_path: Path) -> None:
    local = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    global_config = generated_global_config(tmp_path)

    for event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"):
        assert hook_pairs(global_config, event) == hook_pairs(local, event)

    post_tool = [name for name, _timeout in hook_pairs(local, "PostToolUse")]
    assert post_tool.index("post_tool_extract_memory.py") < post_tool.index("post_tool_checkpoint.py")
    assert post_tool.index("post_tool_checkpoint.py") < post_tool.index("post_tool_cost_ledger.py")

    stop = [name for name, _timeout in hook_pairs(local, "Stop")]
    assert "implementation_notes_guard.py" in stop
    assert stop.index("stop_persist_memory.py") < stop.index("stop_memory_promotion_review.py")
