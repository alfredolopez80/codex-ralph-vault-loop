from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".codex" / "hooks"))

from shared.effective_hook_graph import analyze_hook_graph, role_for_command


def _config(*commands: str) -> dict[str, object]:
    return {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": command} for command in commands]}]}}


def _complete_config(stop_commands: list[str]) -> dict[str, object]:
    def group(command: str) -> list[dict[str, object]]:
        return [{"hooks": [{"type": "command", "command": command}]}]

    return {
        "hooks": {
            "UserPromptSubmit": group("python3 /repo/.codex/hooks/user_prompt_dispatch.py"),
            "PreToolUse": group("python3 /repo/.codex/hooks/pre_tool_dispatch.py"),
            "PostToolUse": group("python3 /repo/.codex/hooks/post_tool_dispatch.py"),
            "Stop": [{"hooks": [{"type": "command", "command": command} for command in stop_commands]}],
        }
    }


def test_project_and_global_same_dispatcher_are_one_semantic_owner() -> None:
    report = analyze_hook_graph(
        [
            ("project", _complete_config(['python3 "/repo/.codex/hooks/stop_dispatch.py"'])),
            (
                "global",
                {
                    "hooks": {
                        "UserPromptSubmit": [{"hooks": [{"command": "python3 /home/.codex/hooks/global_hook_dispatch.py --event UserPromptSubmit --role user_prompt_dispatch"}]}],
                        "PreToolUse": [{"hooks": [{"command": "python3 /home/.codex/hooks/global_hook_dispatch.py --event PreToolUse --role pre_tool_dispatch"}]}],
                        "PostToolUse": [{"hooks": [{"command": "python3 /home/.codex/hooks/global_hook_dispatch.py --event PostToolUse --role post_tool_dispatch"}]}],
                        "Stop": [{"hooks": [{"command": "python3 /home/.codex/hooks/global_hook_dispatch.py --event Stop --role stop_dispatch"}]}],
                    }
                },
            ),
        ]
    )
    stop = next(item for item in report.domains if item.domain == "stop_completion")
    assert report.status == "PASS"
    assert stop.blocking_owners == ("stop_dispatch",)
    assert len(stop.evidence) == 2


def test_different_blocking_roles_fail_and_legacy_wrapper_is_never_silent() -> None:
    report = analyze_hook_graph(
        [("project", _config("bash /repo/.codex/hooks/anti-rationalization-stop.sh", "python3 /repo/.codex/hooks/stop_dispatch.py"))]
    )
    stop = next(item for item in report.domains if item.domain == "stop_completion")
    assert report.status == "FAIL"
    assert report.legacy_wrapper_registered is True
    assert set(stop.blocking_owners) == {"anti_rationalization_stop", "stop_dispatch"}
    assert any("duplicate blocking" in error for error in report.errors)


def test_role_parser_handles_quoted_project_commands() -> None:
    assert role_for_command('python3 "$(git rev-parse --show-toplevel)/.codex/hooks/user_prompt_dispatch.py"') == "user_prompt_dispatch"


def test_plugin_hooks_are_visible_and_unclassified_plugins_warn() -> None:
    project = _complete_config(["python3 /repo/.codex/hooks/stop_dispatch.py"])
    report = analyze_hook_graph(
        [("project", project), ("plugin:replayio", {"hooks": {"Stop": [{"hooks": [{"command": "./scripts/stop_close_and_upload.sh"}]}]}})]
    )
    assert report.status == "WARN"
    stop = next(item for item in report.domains if item.domain == "stop_completion")
    assert stop.blocking_owners == ("stop_dispatch",)
    assert any("plugin:replayio" in warning for warning in report.warnings)
