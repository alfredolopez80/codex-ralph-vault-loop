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


def test_plugin_hooks_are_visible_and_unclassified_guarded_plugins_fail_closed() -> None:
    project = _complete_config(["python3 /repo/.codex/hooks/stop_dispatch.py"])
    report = analyze_hook_graph(
        [("project", project), ("plugin:replayio", {"hooks": {"Stop": [{"hooks": [{"command": "./scripts/stop_close_and_upload.sh"}]}]}})]
    )
    assert report.status == "FAIL"
    stop = next(item for item in report.domains if item.domain == "stop_completion")
    assert stop.blocking_owners == ("stop_dispatch",)
    assert any("plugin:replayio" in error for error in report.errors)


def test_narrow_matcher_does_not_prove_unknown_plugin_is_report_only() -> None:
    report = analyze_hook_graph(
        [
            ("project", _complete_config(["python3 /repo/.codex/hooks/stop_dispatch.py"])),
            (
                "plugin:unknown",
                {
                    "hooks": {
                        "Stop": [{"matcher": "Write", "hooks": [{"command": "./hooks/unknown-stop.sh"}]}]
                    }
                },
            ),
        ]
    )
    assert report.status == "FAIL"
    assert any("trusted classification" in error for error in report.errors)


def test_explicit_plugin_declaration_digest_can_prove_report_only() -> None:
    project = _complete_config(["python3 /repo/.codex/hooks/stop_dispatch.py"])
    plugin = {
        "hooks": {
            "PostToolUse": [
                {"matcher": "Write|Edit", "hooks": [{"command": "./scripts/post_write_figma_parity_check.sh"}]}
            ]
        }
    }
    import hashlib
    import json

    declaration = {
        "source": "plugin:figma@openai-curated",
        "event": "PostToolUse",
        "matcher": "Write|Edit",
        "command": "./scripts/post_write_figma_parity_check.sh",
    }
    context = {
        "bundle_id": "bd2122cb",
        "manifest_digest": "sha256:" + "1" * 64,
        "script_digests": {"./scripts/post_write_figma_parity_check.sh": "sha256:" + "2" * 64},
    }
    declaration["bundle"] = context
    digest = "sha256:" + hashlib.sha256(json.dumps(declaration, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    plugin["_ralph_verified_bundle"] = context
    report = analyze_hook_graph(
        [("project", project), ("plugin:figma@openai-curated", plugin)],
        trusted_report_only={"plugin:figma@openai-curated": {digest: "post_tool_persistence"}},
    )
    assert report.status == "WARN"
    assert any("trusted report-only digest" in warning for warning in report.warnings)
    assert sum(item.source == "plugin:figma@openai-curated" for item in report.entries) == 1


def test_trusted_plugin_digest_binds_bundle_content() -> None:
    plugin = {
        "_ralph_verified_bundle": {
            "bundle_id": "bd2122cb",
            "manifest_digest": "sha256:" + "1" * 64,
            "script_digests": {"./scripts/post_write_figma_parity_check.sh": "sha256:" + "2" * 64},
        },
        "hooks": {"PostToolUse": [{"matcher": "Write|Edit", "hooks": [{"command": "./scripts/post_write_figma_parity_check.sh"}]}]},
    }
    report = analyze_hook_graph(
        [("project", _complete_config(["python3 /repo/.codex/hooks/stop_dispatch.py"])), ("plugin:figma@openai-curated", plugin)],
        trusted_report_only={"plugin:figma@openai-curated": {"sha256:" + "3" * 64: "post_tool_persistence"}},
    )
    assert report.status == "FAIL"
    assert any("trusted classification" in error for error in report.errors)


def test_trusted_plugin_digest_must_match_guarded_event_domain() -> None:
    plugin = {
        "_ralph_verified_bundle": {"bundle_id": "bundle", "manifest_digest": "sha256:" + "1" * 64, "script_digests": {}},
        "hooks": {"Stop": [{"matcher": "Write", "hooks": [{"command": "./scripts/report-only.sh"}]}]},
    }
    import hashlib
    import json

    declaration = {
        "source": "plugin:unknown",
        "event": "Stop",
        "matcher": "Write",
        "command": "./scripts/report-only.sh",
        "bundle": plugin["_ralph_verified_bundle"],
    }
    digest = "sha256:" + hashlib.sha256(json.dumps(declaration, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    report = analyze_hook_graph(
        [("project", _complete_config(["python3 /repo/.codex/hooks/stop_dispatch.py"])), ("plugin:unknown", plugin)],
        trusted_report_only={"plugin:unknown": {digest: "post_tool_persistence"}},
    )
    assert report.status == "FAIL"
    assert any("trusted classification" in error for error in report.errors)
