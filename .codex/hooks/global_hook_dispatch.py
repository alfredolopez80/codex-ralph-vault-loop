#!/usr/bin/env python3
"""Run a global hook only when the active project does not provide that role."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from shared.active_context import active_context_from_payload

HOOK_DIR = Path(__file__).resolve().parent
ROLE_COMMANDS: dict[tuple[str, str], tuple[str, ...]] = {
    ("SessionStart", "session_start_wakeup"): ("session_start_wakeup.py",),
    ("UserPromptSubmit", "universal_prompt_classifier"): ("universal-prompt-classifier.sh",),
    ("UserPromptSubmit", "sol_advisor_prompt_state"): ("sol_advisor_prompt_state.py",),
    ("UserPromptSubmit", "user_prompt_capture"): ("user_prompt_capture.py",),
    ("UserPromptSubmit", "user_prompt_improve"): ("user_prompt_improve.py",),
    ("UserPromptSubmit", "continuity_prompt_context"): ("continuity_prompt_context.py",),
    ("PreToolUse", "pre_tool_guard"): ("pre_tool_guard.py",),
    ("PreToolUse", "subagent_routing_pretool_guard"): ("subagent_routing_pretool_guard.py",),
    ("PreToolUse", "sol_advisor_pretool_guard"): ("sol_advisor_pretool_guard.py",),
    ("PostToolUse", "post_tool_dispatch"): ("post_tool_dispatch.py",),
    # Compatibility aliases for callers that still invoke a historical role
    # directly.  The project/global hook configuration registers only the
    # consolidated dispatcher above.
    ("PostToolUse", "file_line_guard_post_tool"): ("file_line_guard.py", "--event", "PostToolUse"),
    ("PostToolUse", "shaping_ripple"): ("shaping_ripple.py",),
    ("PostToolUse", "post_tool_extract_memory"): ("post_tool_extract_memory.py",),
    ("PostToolUse", "post_tool_checkpoint"): ("post_tool_checkpoint.py",),
    ("PostToolUse", "sol_advisor_observer"): ("sol_advisor_observer.py",),
    ("PostToolUse", "post_tool_cost_ledger"): ("post_tool_cost_ledger.py",),
    ("SubagentStart", "sol_advisor_subagent_context"): ("sol_advisor_subagent_context.py",),
    ("SubagentStop", "sol_advisor_subagent_stop"): ("sol_advisor_subagent_stop.py",),
    ("Stop", "stop_dispatch"): ("stop_dispatch.py",),
    # Compatibility aliases for direct historical diagnostics. The project
    # and global configurations register only stop_dispatch.
    ("Stop", "anti_rationalization_stop"): ("anti-rationalization-stop.sh",),
    ("Stop", "ralph_stop_quality_gate"): ("ralph-stop-quality-gate.sh",),
    ("Stop", "file_line_guard_stop"): ("file_line_guard.py", "--event", "Stop"),
    ("Stop", "stop_route_decision_warn"): ("stop_route_decision_warn.py",),
    ("Stop", "implementation_notes_guard"): ("implementation_notes_guard.py",),
    ("Stop", "sol_advisor_stop_guard"): ("sol_advisor_stop_guard.py",),
    ("Stop", "stop_persist_memory"): ("stop_persist_memory.py",),
    ("Stop", "stop_memory_promotion_review"): ("stop_memory_promotion_review.py",),
}


def parse_payload(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


ROLE_BY_FILENAME = {
    "session_start_wakeup.py": "session_start_wakeup",
    "universal-prompt-classifier.sh": "universal_prompt_classifier",
    "sol_advisor_prompt_state.py": "sol_advisor_prompt_state",
    "user_prompt_capture.py": "user_prompt_capture",
    "user_prompt_improve.py": "user_prompt_improve",
    "continuity_prompt_context.py": "continuity_prompt_context",
    "pre_tool_guard.py": "pre_tool_guard",
    "subagent_routing_pretool_guard.py": "subagent_routing_pretool_guard",
    "sol_advisor_pretool_guard.py": "sol_advisor_pretool_guard",
    "post_tool_dispatch.py": "post_tool_dispatch",
    "shaping_ripple.py": "shaping_ripple",
    "post_tool_extract_memory.py": "post_tool_extract_memory",
    "post_tool_checkpoint.py": "post_tool_checkpoint",
    "sol_advisor_observer.py": "sol_advisor_observer",
    "sol_advisor_subagent_context.py": "sol_advisor_subagent_context",
    "sol_advisor_subagent_stop.py": "sol_advisor_subagent_stop",
    "post_tool_cost_ledger.py": "post_tool_cost_ledger",
    "stop_dispatch.py": "stop_dispatch",
    "anti-rationalization-stop.sh": "anti_rationalization_stop",
    "ralph-stop-quality-gate.sh": "ralph_stop_quality_gate",
    "stop_route_decision_warn.py": "stop_route_decision_warn",
    "implementation_notes_guard.py": "implementation_notes_guard",
    "sol_advisor_stop_guard.py": "sol_advisor_stop_guard",
    "stop_persist_memory.py": "stop_persist_memory",
    "stop_memory_promotion_review.py": "stop_memory_promotion_review",
}
DISPATCH_ROLE_RE = re.compile(r"global_hook_dispatch\.py\s+--event\s+(\S+)\s+--role\s+([A-Za-z0-9_]+)")
ROLE_MATCHERS: dict[tuple[str, str], str] = {
    ("PostToolUse", "post_tool_dispatch"): ".*",
}


def role_for_command(event: str, command: object) -> str | None:
    if not isinstance(command, str):
        return None
    dispatcher = DISPATCH_ROLE_RE.search(command)
    if dispatcher and dispatcher.group(1) == event:
        return dispatcher.group(2)
    if "file_line_guard.py" in command:
        if event == "PostToolUse" and re.search(r"--event\s+PostToolUse\b", command):
            return "file_line_guard_post_tool"
        if event == "Stop" and re.search(r"--event\s+Stop\b", command):
            return "file_line_guard_stop"
        return None
    for filename, role in ROLE_BY_FILENAME.items():
        if filename in command:
            return role
    return None


def project_role_signatures(workspace: Path, event: str) -> set[tuple[str, str]]:
    config_path = workspace / ".codex" / "hooks.json"
    try:
        if not config_path.is_file() or not config_path.resolve().is_relative_to(workspace.resolve()):
            return set()
        config = json.loads(config_path.read_text(encoding="utf-8"))
        hooks = config.get("hooks", {})
        groups = hooks.get(event, []) if isinstance(hooks, dict) else []
    except (OSError, json.JSONDecodeError, ValueError):
        return set()
    if not isinstance(groups, list):
        return set()

    roles: set[tuple[str, str]] = set()
    for group in groups:
        matcher = str(group.get("matcher", "")) if isinstance(group, dict) else ""
        entries = group.get("hooks", []) if isinstance(group, dict) else []
        if not isinstance(entries, list):
            continue
        for entry in entries:
            role = role_for_command(event, entry.get("command") if isinstance(entry, dict) else None)
            if role:
                roles.add((role, matcher))
    return roles


def project_roles(workspace: Path, event: str) -> set[str]:
    return {role for role, _matcher in project_role_signatures(workspace, event)}


def invoke_child(event: str, role: str, raw: str, workspace: Path) -> int:
    child = ROLE_COMMANDS[(event, role)]
    script = HOOK_DIR / child[0]
    command = ["bash", str(script), *child[1:]] if script.suffix == ".sh" else [sys.executable, str(script), *child[1:]]
    try:
        child_env = os.environ.copy()
        child_env["RALPH_HOOK_SCOPE"] = "global"
        completed = subprocess.run(
            command,
            cwd=workspace if workspace.is_dir() else None,
            env=child_env,
            input=raw,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return 0
    if completed.stdout:
        sys.stdout.write(completed.stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Dispatch one allowlisted Ralph global hook role.")
    parser.add_argument("--event", required=True)
    parser.add_argument("--role", required=True)
    args = parser.parse_args()
    key = (args.event, args.role)
    if key not in ROLE_COMMANDS:
        return 0

    raw = sys.stdin.read()
    context = active_context_from_payload(parse_payload(raw))
    expected_matcher = ROLE_MATCHERS.get(key, "")
    if (args.role, expected_matcher) in project_role_signatures(context.workspace_root, args.event):
        return 0
    return invoke_child(args.event, args.role, raw, context.workspace_root)


if __name__ == "__main__":
    raise SystemExit(main())
