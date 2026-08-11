"""Pure hot-path predicates shared by v4 hook dispatchers.

The predicate is deliberately conservative.  It only grants the successful
read no-op when there is no stream, write, agent, external, test, approval,
route, evidence, or other material signal.  PreToolUse remains an independent
always-on guard and is never called through this fast path.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Any, Mapping


READ_EXECUTABLES = frozenset({"cat", "head", "tail", "rg", "grep", "find", "fd", "ls", "pwd", "stat", "file", "wc"})
MAX_COMMAND_BYTES = 4_096
READ_TOOL_WORDS = frozenset({"read", "search", "find", "list", "glob", "get", "stat", "inspect", "status", "diff", "log", "show"})
LOCAL_READ_TOOL_NAMES = frozenset({"read", "grep", "glob", "list", "find", "stat", "inspect", "status", "git_status", "git_diff", "git_log", "git_show"})
LOCAL_COMMAND_TOOL_NAMES = frozenset({"exec_command", "shell", "bash", "sh", "zsh", "terminal", "run_command"})
WRITE_WORDS = frozenset({"apply_patch", "edit", "write", "save", "create", "update", "delete", "remove", "move", "rename", "copy", "mkdir", "touch"})
MATERIAL_MARKERS = re.compile(
    r"\b(ROUTE_DECISION|APPROVAL_NEEDED|MATERIAL_CHANGE|EVIDENCE|BLOCKER|P0|P1|USER_DECISION|RED_LEAK|WRONG_WORKTREE)\b",
    re.I,
)


@dataclass(frozen=True)
class HotPathResult:
    eligible: bool
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {"eligible": self.eligible, "reason": self.reason}


def successful_read_fast_path(payload: Mapping[str, object]) -> HotPathResult:
    """Return whether a PostToolUse event is a physical no-op candidate."""

    if payload.get("hook_event_name") not in (None, "PostToolUse"):
        return HotPathResult(False, "wrong_event")
    response = _response(payload)
    if _is_partial(payload, response):
        return HotPathResult(False, "partial_stream")
    if _success(payload, response) is not True:
        return HotPathResult(False, "not_successful")
    name = str(payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "").strip().lower()
    command = _command(payload)
    if not name:
        return HotPathResult(False, "tool_name_missing")
    if _is_agent_or_external(name):
        return HotPathResult(False, "agent_or_external")
    if _is_write(name, command):
        return HotPathResult(False, "write_signal")
    if _is_test(command, name):
        return HotPathResult(False, "test_or_build")
    if not _is_read(name, command):
        return HotPathResult(False, "not_read_only")
    rendered, complete = _bounded_output(payload, response)
    if not complete:
        return HotPathResult(False, "materiality_unknown")
    if MATERIAL_MARKERS.search(rendered):
        return HotPathResult(False, "material_signal")
    return HotPathResult(True, "successful_read_unchanged")


def _response(payload: Mapping[str, object]) -> Mapping[str, object]:
    value = payload.get("tool_response") or payload.get("toolResponse") or payload.get("response")
    return value if isinstance(value, Mapping) else {}


def _success(payload: Mapping[str, object], response: Mapping[str, object]) -> bool | None:
    value = payload.get("success")
    payload_success = value if isinstance(value, bool) else None
    exit_code = response.get("exit_code") if "exit_code" in response else response.get("exitCode")
    response_success = (exit_code == 0) if isinstance(exit_code, int) and not isinstance(exit_code, bool) else None
    if payload_success is not None and response_success is not None and payload_success != response_success:
        return None
    return payload_success if payload_success is not None else response_success


def _is_partial(payload: Mapping[str, object], response: Mapping[str, object]) -> bool:
    for value in (payload.get("result_stage"), payload.get("stage"), payload.get("stream_status"), response.get("result_stage"), response.get("stage")):
        if str(value or "").strip().lower() in {"partial", "streaming", "inflight", "running"}:
            return True
    # A session id identifies an interactive stream.  Even if a wrapper also
    # reports success, keep the event on the normal path until the terminal
    # poll has been classified by the existing stream reducer.
    return bool(response.get("session_id") or response.get("sessionId"))


def _command(payload: Mapping[str, object]) -> str:
    data = payload.get("tool_input") or payload.get("toolInput") or payload.get("input")
    nested = data if isinstance(data, Mapping) else {}
    for value in (payload.get("command"), payload.get("cmd"), nested.get("command"), nested.get("cmd")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return []


def _is_read(name: str, command: str) -> bool:
    components = set(re.split(r"[^a-z0-9]+", name))
    # A command-shaped payload from a non-local tool is still external.  Do
    # not let a web/app/plugin tool smuggle a safe-looking shell command into
    # the physical no-op path.
    if name and name not in LOCAL_READ_TOOL_NAMES and name not in LOCAL_COMMAND_TOOL_NAMES:
        return False
    if len(command.encode("utf-8", errors="replace")) > MAX_COMMAND_BYTES:
        return False
    if any(marker in command for marker in ("$(", "`", "\n", "\r", ">", "<", "|", ";", "&", "$")):
        return False
    tokens = _tokens(command)
    if not command:
        return name in LOCAL_READ_TOOL_NAMES
    if not tokens or any(token in {"&&", "||", ";", "|", ">", ">>", "<", "2>", "2>>"} for token in tokens):
        return False
    # Basename allowlisting is unsafe: ``./cat`` or a repo-local ``git`` can
    # be an arbitrary mutator.  Only the exact bare executable token is
    # eligible; trusted absolute paths can be added deliberately to this
    # closed-world list later without accepting arbitrary path aliases.
    if "/" in tokens[0] or "\\" in tokens[0]:
        return False
    executable = tokens[0].lower()
    if executable in READ_EXECUTABLES and _has_mutating_option(executable, tokens[1:]):
        return False
    if executable in READ_EXECUTABLES:
        return True
    if executable != "git" or len(tokens) < 2 or tokens[1].startswith("-"):
        return False
    subcommand = tokens[1].lower()
    if subcommand in {"status", "diff", "log", "show", "rev-parse", "ls-files"}:
        return not _git_output_or_mutation(tokens[2:])
    if subcommand == "branch":
        return _git_branch_read_only(tokens[2:])
    if subcommand == "remote":
        return len(tokens) == 2 or tokens[2].lower() in {"-v", "--verbose", "show", "get-url"}
    return False


def is_read_only_command(command: str) -> bool:
    """Expose the same closed-world command classifier to PostTool dispatch."""

    return _is_read("", command)


def _git_output_or_mutation(arguments: list[str]) -> bool:
    """Reject Git options that can write files or mutate repository state."""

    return any(
        argument in {"--output", "-o", "--edit", "--apply", "--cached", "--index"}
        or argument.startswith("--output=")
        or argument in {"--ext-diff", "--textconv"}
        for argument in arguments
    )


def _git_branch_read_only(arguments: list[str]) -> bool:
    """Allow only branch listing forms; creation, deletion, and rename are not reads."""

    if not arguments:
        return True
    mutating = {
        "-d",
        "-D",
        "--delete",
        "-m",
        "-M",
        "--move",
        "-c",
        "-C",
        "--copy",
        "--edit-description",
        "--set-upstream-to",
        "--unset-upstream",
    }
    if any(
        argument in mutating
        or argument.startswith("--delete=")
        or argument.startswith("--set-upstream-to")
        or argument.startswith("--unset-upstream")
        for argument in arguments
    ):
        return False
    # A positional branch name without --list is a create/rename request.
    safe_flags = {
        "-a",
        "-r",
        "--all",
        "--remotes",
        "--list",
        "--contains",
        "--no-contains",
        "--merged",
        "--no-merged",
        "--column",
        "--no-column",
        "--sort",
        "--format",
        "--color",
        "--no-color",
    }
    return all(
        argument.startswith("-")
        and (
            argument in safe_flags
            or any(argument.startswith(prefix + "=") for prefix in ("--sort", "--format", "--contains", "--no-contains", "--merged", "--no-merged", "--color"))
        )
        for argument in arguments
    )


def _has_mutating_option(executable: str, arguments: list[str]) -> bool:
    """Reject read-looking commands with known write-capable options."""

    if executable == "sed":
        # GNU/BSD sed both support -i/--in-place; a suffix such as -i.bak is
        # also a write.  The ``w`` command writes from inside a sed program.
        for index, argument in enumerate(arguments):
            script = ""
            if argument in {"-e", "--expression"} and index + 1 < len(arguments):
                script = arguments[index + 1]
            elif argument.startswith("-e") and argument != "-e":
                script = argument[2:]
            elif argument.startswith("--expression="):
                script = argument.split("=", 1)[1]
            if (
                argument == "--in-place"
                or argument.startswith("-i")
                or _sed_program_writes(argument)
                or _sed_program_executes(argument)
                or (script and (_sed_program_writes(script) or _sed_program_executes(script)))
            ):
                return True
        return False
    if executable in {"find", "fd"}:
        return any(
            argument in {
                "-delete",
                "--delete",
                "-d",
                "-exec",
                "-execdir",
                "-ok",
                "-okdir",
                "-fprint",
                "-fls",
                "-fprintf",
                "-x",
                "-X",
            }
            or argument.startswith("--exec")
            or argument.startswith("-fprint")
            for argument in arguments
        )
    if executable == "file":
        return any(argument in {"--compile", "-C"} or argument.startswith("--compile=") for argument in arguments)
    if executable == "rg":
        # Long options may carry their value inline and short ``-r`` may be
        # attached to it; every spelling mutates the command result.
        return any(
            argument in {"--replace", "-r"}
            or argument.startswith("--replace=")
            or (argument.startswith("-r") and argument != "-r")
            # ``--pre`` executes a caller-selected preprocessor and therefore
            # is not a pure read, even when ripgrep itself only emits matches.
            or argument == "--pre"
            or argument.startswith("--pre=")
            or argument == "--pre-glob"
            or argument == "--hostname-bin"
            or argument.startswith("--hostname-bin=")
            for argument in arguments
        )
    return False


def _sed_program_writes(argument: str) -> bool:
    if argument.startswith("-"):
        return False
    # A bounded conservative check for sed's ``w file`` command.  Ordinary
    # print/substitution programs do not contain a standalone w command.
    return bool(re.search(r"(?:^|[;{} /])\s*(?:\d+(?:,\d+)?)?w(?:\s|$)", argument))


def _sed_program_executes(argument: str) -> bool:
    if argument.startswith("-"):
        return False
    return bool(re.search(r"(?:^|[;{} /])\s*(?:\d+(?:,\d+)?)?e(?:\s|$)", argument))


def _is_write(name: str, command: str) -> bool:
    components = set(re.split(r"[^a-z0-9]+", name))
    if components & WRITE_WORDS or "*** begin patch" in command.lower():
        return True
    tokens = _tokens(command)
    if any(token in {"&&", "||", ";", "|"} for token in tokens):
        # Mixed shell syntax is not provably a successful read-only action;
        # keep it out of the physical no-op path.
        return True
    return any(token in {">", ">>", "2>", "2>>", "<"} for token in tokens)


def _is_agent_or_external(name: str) -> bool:
    return any(marker in name for marker in ("agent", "advisor", "spawn", "write_stdin", "mcp__", "mcp."))


def _is_test(command: str, name: str) -> bool:
    lowered = f"{name} {command}".lower()
    return any(marker in lowered for marker in ("pytest", "npm test", "pnpm test", "make test", "build", "typecheck", "lint"))


def _bounded_output(payload: Mapping[str, object], response: Mapping[str, object]) -> tuple[str, bool]:
    values: list[str] = []
    complete = True

    def visit(value: object, *, depth: int = 0) -> None:
        nonlocal complete
        if depth > 4:
            complete = False
            return
        if isinstance(value, str):
            if len(value) > 2_000:
                complete = False
            values.append(value[:2_000])
            return
        if isinstance(value, Mapping):
            for item in value.values():
                visit(item, depth=depth + 1)
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                visit(item, depth=depth + 1)
            return
        if value is not None and not isinstance(value, (bool, int, float)):
            # Unknown structured response content is not safe to classify as
            # unchanged because it may contain a deferred material signal.
            complete = False

    for source in (payload, response):
        if isinstance(source, Mapping):
            for key in ("output", "stdout", "stderr", "result", "message", "content"):
                if key in source:
                    visit(source[key])
    return "\n".join(values), complete


__all__ = ["HotPathResult", "is_read_only_command", "successful_read_fast_path"]
