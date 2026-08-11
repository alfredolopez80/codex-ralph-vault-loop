#!/usr/bin/env python3
"""Single-read, selective PostToolUse dispatcher.

This process composes the existing policies.  It is an observation boundary:
it can report a supported block/feedback response, but it cannot undo a tool
side effect that already happened.  All state written here is bounded,
project-scoped, and content-free.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.active_context import active_context_from_payload
from shared.file_line_candidates import candidate_paths
from file_line_guard import evaluate as file_line_evaluate
from shared.paths import ralph_home, read_hook_input, write_json
from post_tool_checkpoint import run as checkpoint_run
from post_tool_cost_ledger import record as cost_record
from post_tool_extract_memory import raw_learning_candidate, run as memory_run
from shared.post_tool_ledger import append_cost_event
from shared.persistence_metrics import WriteAccumulator, WriteResult
from shared.progress_hook import cheap_lookup
from shared.progress_runtime import structured_validation, validation_transition
from shared.convergent_hooks import is_read_only_command, successful_read_fast_path
from shared.execution_policy import configured_activation_mode
# Kept as an explicit benchmark/diagnostic compatibility symbol.  The normal
# dispatcher never calls it; production byte attribution comes from writers.
from shared.post_tool_state import append_metric, dedupe_claim, directory_bytes, result_stage
from shared.redaction import is_red, safe_preview
from shared.runtime_observability import record_event
from shared.runtime_profile import is_progress_maintenance
from shaping_ripple import evaluate as shaping_evaluate
from sol_advisor_observer import run as advisor_run
from shared.tool_result import success_from_payload

TEST_MARKERS = ("test", "pytest", "npm test", "pnpm test", "make test", "build", "typecheck", "lint")
READ_WORDS = {"cat", "head", "tail", "less", "more", "sed", "rg", "grep", "find", "fd", "ls", "pwd", "stat", "file", "wc"}
READ_TOOL_WORDS = ("read", "search", "find", "list", "glob", "get", "stat", "inspect", "status", "diff", "log", "show")
WRITE_TOOL_WORDS = ("apply_patch", "edit", "write", "save", "create", "update", "delete", "remove", "move", "rename", "copy", "mkdir", "touch")
AGENT_WORDS = ("spawn_agent", "spawn-agent", "agent", "advisor", "wait_agent", "send_input", "write_stdin")
EXTERNAL_WORDS = ("mcp__", "mcp.", "ralph_coding_models", "zai_", "minimax", "web_search")


@dataclass(frozen=True)
class ToolClass:
    name: str
    family: str
    command: str
    success: bool | None
    read_only: bool
    write: bool
    test_like: bool
    agent: bool
    external: bool


def _tool_input(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("tool_input", "toolInput", "input"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _tool_name(payload: dict[str, Any]) -> str:
    value = payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "unknown"
    return safe_preview(value, 120)


def _command(payload: dict[str, Any]) -> str:
    data = _tool_input(payload)
    for value in (payload.get("command"), payload.get("cmd"), data.get("command"), data.get("cmd")):
        if isinstance(value, str) and value.strip():
            return safe_preview(value, 500)
    return ""


def _tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return []


def _command_is_read(command: str) -> bool:
    return is_read_only_command(command)


def _command_is_test(command: str) -> bool:
    lowered = command.lower()
    return any(marker in lowered for marker in TEST_MARKERS)


def _name_has_word(lowered: str, words: tuple[str, ...]) -> bool:
    components = re.split(r"[^a-z0-9]+", lowered)
    return any(component == word or component.startswith(f"{word}_") for component in components for word in words)


def classify_tool(payload: dict[str, Any]) -> ToolClass:
    name = _tool_name(payload)
    lowered = name.lower()
    command = _command(payload)
    patch = isinstance(_tool_input(payload).get("patch"), str) or "*** begin patch" in command.lower()
    agent = _name_has_word(lowered, AGENT_WORDS)
    external = any(word in lowered for word in EXTERNAL_WORDS)
    read_name = _name_has_word(lowered, READ_TOOL_WORDS)
    write_name = patch or _name_has_word(lowered, WRITE_TOOL_WORDS)
    test_like = _command_is_test(command) or _name_has_word(lowered, ("test", "build", "lint"))
    command_read = bool(command) and _command_is_read(command)
    read_only = read_name or command_read
    if agent:
        family = "agent"
    elif external:
        family = "external_mcp"
    elif test_like:
        family = "test_build_lint"
    elif write_name or (command and not read_only):
        family = "write"
    elif read_only:
        family = "read"
    else:
        family = "unknown"
    write = not read_only and (write_name or bool(command) or family == "unknown")
    if test_like and not write_name and command_read is False:
        write = False
    return ToolClass(name, family, command, success_from_payload(payload), read_only, write, test_like, agent, external)


def _output_marker(payload: dict[str, Any], marker: str) -> bool:
    for key in ("output", "stdout", "stderr", "result", "message"):
        value = payload.get(key)
        if isinstance(value, str) and marker in value:
            return True
    response = payload.get("tool_response") or payload.get("toolResponse")
    if isinstance(response, dict):
        return any(isinstance(response.get(key), str) and marker in response[key] for key in ("output", "stdout", "stderr", "result", "message"))
    return False


def _should_file_line(tool: ToolClass) -> bool:
    return tool.write and not tool.read_only


def _has_markdown_path(payload: dict[str, Any]) -> bool:
    return any(path.suffix.lower() in {".md", ".markdown"} for path in candidate_paths(payload))


def _should_shaping(payload: dict[str, Any], tool: ToolClass, storage_ok: bool) -> bool:
    return storage_ok and _should_file_line(tool) and _has_markdown_path(payload)


def _should_memory(payload: dict[str, Any], tool: ToolClass) -> bool:
    if tool.success is not True or tool.read_only:
        return False
    material = raw_learning_candidate(payload)
    return bool(material.strip()) and not is_red(material)


def _should_checkpoint(tool: ToolClass) -> bool:
    return tool.success is False or tool.agent or tool.test_like or tool.write or (tool.external and not tool.read_only)


def _should_advisor(payload: dict[str, Any], tool: ToolClass) -> bool:
    if is_progress_maintenance(
        payload.get("origin") or _tool_input(payload).get("origin"),
        payload.get("intent") or _tool_input(payload).get("intent"),
    ):
        return False
    # Failed objective commands are routing evidence for the existing Sol
    # observer (two bounded failures can make a stuck route eligible). This is
    # still selective: successful test/build output and ordinary read failures
    # do not invoke the observer.
    failed_objective = tool.success is False and tool.test_like
    return tool.agent or tool.external or failed_objective or _output_marker(payload, "ROUTE_DECISION") or _output_marker(payload, "APPROVAL_NEEDED")


def _response_bytes(response: dict[str, Any] | None) -> int:
    return len(json.dumps(response, ensure_ascii=True, sort_keys=True).encode("utf-8")) if response else 0


def _runtime_safe() -> bool:
    configured = ralph_home()
    return not configured.is_symlink()


def _result_from_mapping(value: object) -> WriteResult:
    """Convert a checkpoint-style result without retaining payload content."""
    if not isinstance(value, dict):
        return WriteResult.unknown()
    bytes_written = value.get("bytes_written")
    files = value.get("files_written")
    if bytes_written is None or value.get("persistence_bytes_known", bytes_written is not None) is False:
        return WriteResult.unknown(changed=bool(value.get("changed")))
    try:
        file_names = tuple(str(item) for item in files) if isinstance(files, (list, tuple)) else ()
        return WriteResult(
            changed=bool(value.get("changed")),
            bytes_written=max(0, int(bytes_written)),
            files_written=file_names,
            replacements=max(0, int(value.get("replacements", 0) or 0)),
            appends=max(0, int(value.get("appends", 0) or 0)),
            fsync_publications=max(0, int(value.get("fsync_publications", 0) or 0)),
        )
    except (TypeError, ValueError):
        return WriteResult.unknown(changed=bool(value.get("changed")))


def dispatch(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not payload or not isinstance(payload, dict):
        return None
    if payload.get("hook_event_name") not in (None, "PostToolUse"):
        return None
    started = time.perf_counter_ns()
    tool = classify_tool(payload)
    context = active_context_from_payload(payload, resolve_git=False)
    # In enforce mode a proven successful, non-material read is a physical
    # no-op.  This return happens before context, ledger, checkpoint, memory,
    # advisor, or observability writers.  PreToolUse is a separate dispatcher
    # and remains active for the corresponding tool invocation.
    try:
        if configured_activation_mode(workspace_root=context.workspace_root) == "enforce" and successful_read_fast_path(payload).eligible:
            return None
    except Exception:
        # Invalid activation metadata must never create a bypass; retain the
        # existing conservative dispatcher behavior and let normal gates run.
        pass
    stage = result_stage(payload)
    pending_stream = stage == "partial"
    persistence_allowed = _runtime_safe()
    accounting = WriteAccumulator()
    components: list[str] = []
    errors: list[str] = []
    response: dict[str, Any] | None = None
    considered: list[str] = []
    # The structured gate detector owns recognition of direct lint/typecheck
    # runners (ruff, mypy, tsc, and friends).  Do not gate that call behind the
    # broader heuristic classifier: a recognized validation command may not
    # contain the generic "test"/"build"/"lint" marker.
    structured_gate = structured_validation(payload) if persistence_allowed and not pending_stream else None
    if not pending_stream and _should_file_line(tool):
        considered.append("file_line_guard")
    if not pending_stream and _should_shaping(payload, tool, persistence_allowed):
        considered.append("shaping_ripple")
    if not pending_stream and _should_memory(payload, tool):
        considered.append("post_tool_extract_memory")
    if not pending_stream and _should_checkpoint(tool):
        considered.append("post_tool_checkpoint")
    if structured_gate is not None:
        considered.append("progress_validation")
    if not pending_stream and _should_advisor(payload, tool):
        considered.append("sol_advisor_observer")
    if persistence_allowed and not pending_stream:
        considered.append("post_tool_cost_ledger")

    with dedupe_claim(context, payload) as claim:
        duplicate = claim.duplicate
        if duplicate:
            components = ["dedupe"]
        elif pending_stream:
            components = ["stream_pending"]
        else:
            if structured_gate is not None:
                try:
                    progress_lookup = cheap_lookup(context, payload)
                    transition = validation_transition(payload, context, progress_lookup)
                    if transition.gate:
                        components.append("progress_validation")
                        accounting.add(transition.result)
                except Exception:
                    # Progress is a narrow derivative of a structured result;
                    # an unavailable progress store must not alter the
                    # existing file-line, shaping, memory, or safety paths.
                    errors.append("progress_validation")
            if _should_file_line(tool):
                components.append("file_line_guard")
                try:
                    response = file_line_evaluate(payload, "PostToolUse")
                except Exception:
                    errors.append("file_line_guard")
            if response is None and _should_shaping(payload, tool, persistence_allowed):
                try:
                    shaping = shaping_evaluate(payload)
                    if shaping:
                        components.append("shaping_ripple")
                        response = shaping
                    elif shaping is None:
                        components.append("shaping_ripple")
                        # A report-only shaping warning may have appended a
                        # local record, but that compatibility writer does
                        # not expose bounded metrics yet.
                        accounting.add(None)
                except Exception:
                    errors.append("shaping_ripple")
            if response is None and persistence_allowed and _should_memory(payload, tool):
                components.append("post_tool_extract_memory")
                try:
                    accounting.add(memory_run(payload, context))
                except Exception:
                    errors.append("post_tool_extract_memory")
            if response is None and persistence_allowed and _should_checkpoint(tool):
                components.append("post_tool_checkpoint")
                try:
                    accounting.add(_result_from_mapping(checkpoint_run(payload, context)))
                except Exception:
                    errors.append("post_tool_checkpoint")
            if response is None and persistence_allowed and _should_advisor(payload, tool):
                components.append("sol_advisor_observer")
                try:
                    advisor_run(payload)
                    # The advisor compatibility writer has no bounded result
                    # boundary; leave the aggregate explicitly unknown.
                    accounting.add(None)
                except Exception:
                    errors.append("sol_advisor_observer")
            if persistence_allowed:
                components.append("post_tool_cost_ledger")
                try:
                    accounting.add(append_cost_event(cost_record(payload)))
                except Exception:
                    errors.append("post_tool_cost_ledger")

        accounting.add(claim.write_result)
        persistence_metrics = accounting.as_dict()
        append_metric(
            context,
            {
                "event": "PostToolUse",
                "project_id": context.project_id,
                "session_id": context.session_id,
                "tool_family": tool.family,
                "tool_name": tool.name,
                "success": tool.success,
                "components": components[:12],
                "component_errors": errors[:8],
                "duplicate_suppressed": duplicate,
                "runtime_ms": round((time.perf_counter_ns() - started) / 1_000_000, 3),
                "child_process_count": 0,
                "output_bytes": _response_bytes(response),
                "persisted_bytes_delta": persistence_metrics["persistence_bytes"],
                "persistence_bytes_known": persistence_metrics["persistence_bytes_known"],
                "persistence_files_written": persistence_metrics["files_written"],
                "persistence_replacements": persistence_metrics["replacements"],
                "persistence_appends": persistence_metrics["appends"],
                "fsync_publications": persistence_metrics["fsync_publications"],
            },
        )
        record_event(
            context,
            payload,
            event="post_tool",
            dispatcher="post_tool_dispatch",
            duration_ns=time.perf_counter_ns() - started,
            process_count=1,
            child_process_count=0,
            tool_family=tool.family,
            components_considered=considered,
            components_executed=components,
            components_skipped=[item for item in considered if item not in components],
            skipped_reason=errors or (["duplicate"] if duplicate else []),
            success=tool.success,
            output_bytes=_response_bytes(response),
            persistence_bytes=persistence_metrics["persistence_bytes"],
            persistence_bytes_known=persistence_metrics["persistence_bytes_known"],
            persistence_files_written=persistence_metrics["files_written"],
            persistence_replacements=persistence_metrics["replacements"],
            persistence_appends=persistence_metrics["appends"],
            fsync_publications=persistence_metrics["fsync_publications"],
            duplicate_suppressed=duplicate,
            block_reason_code=(response or {}).get("reason_code") if response else [],
            scenario=payload.get("scenario"),
        )
    return response


def main() -> int:
    payload = read_hook_input()
    try:
        response = dispatch(payload)
    except Exception:
        return 0
    if response:
        write_json(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
