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
from pathlib import Path
from typing import Any, Mapping


READ_EXECUTABLES = frozenset({"cat", "head", "tail", "less", "more", "sed", "rg", "grep", "find", "fd", "ls", "pwd", "stat", "file", "wc"})
READ_TOOL_WORDS = frozenset({"read", "search", "find", "list", "glob", "get", "stat", "inspect", "status", "diff", "log", "show"})
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
    if _is_agent_or_external(name):
        return HotPathResult(False, "agent_or_external")
    if _is_write(name, command):
        return HotPathResult(False, "write_signal")
    if _is_test(command, name):
        return HotPathResult(False, "test_or_build")
    if not _is_read(name, command):
        return HotPathResult(False, "not_read_only")
    rendered = _bounded_output(payload, response)
    if MATERIAL_MARKERS.search(rendered):
        return HotPathResult(False, "material_signal")
    return HotPathResult(True, "successful_read_unchanged")


def _response(payload: Mapping[str, object]) -> Mapping[str, object]:
    value = payload.get("tool_response") or payload.get("toolResponse") or payload.get("response")
    return value if isinstance(value, Mapping) else {}


def _success(payload: Mapping[str, object], response: Mapping[str, object]) -> bool | None:
    value = payload.get("success")
    if isinstance(value, bool):
        return value
    exit_code = response.get("exit_code") if "exit_code" in response else response.get("exitCode")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        return exit_code == 0
    return None


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
            return value.strip()[:500]
    return ""


def _tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return []


def _is_read(name: str, command: str) -> bool:
    components = set(re.split(r"[^a-z0-9]+", name))
    if components & READ_TOOL_WORDS:
        return True
    tokens = _tokens(command)
    if not tokens or any(token in {"&&", "||", ";", "|", ">", ">>", "<", "2>", "2>>"} for token in tokens):
        return False
    executable = Path(tokens[0]).name.lower()
    if executable in READ_EXECUTABLES and _has_mutating_option(executable, tokens[1:]):
        return False
    if executable in READ_EXECUTABLES:
        return True
    return executable == "git" and len(tokens) > 1 and tokens[1].lower() in {"status", "diff", "log", "show", "branch", "rev-parse", "ls-files", "remote"}


def _has_mutating_option(executable: str, arguments: list[str]) -> bool:
    """Reject read-looking commands with known write-capable options."""

    if executable == "sed":
        # GNU/BSD sed both support -i/--in-place; a suffix such as -i.bak is
        # also a write.  The ``w`` command writes from inside a sed program.
        return any(argument == "--in-place" or argument.startswith("-i") or _sed_program_writes(argument) for argument in arguments)
    if executable in {"find", "fd"}:
        return any(argument in {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fls", "-fprintf"} for argument in arguments)
    if executable == "rg":
        return any(argument in {"--replace", "-r"} for argument in arguments)
    return False


def _sed_program_writes(argument: str) -> bool:
    if argument.startswith("-"):
        return False
    # A bounded conservative check for sed's ``w file`` command.  Ordinary
    # print/substitution programs do not contain a standalone w command.
    return bool(re.search(r"(?:^|[;{}])\s*(?:\d+(?:,\d+)?)?w(?:\s|$)", argument))


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


def _bounded_output(payload: Mapping[str, object], response: Mapping[str, object]) -> str:
    values: list[str] = []
    for source in (payload, response):
        for key in ("output", "stdout", "stderr", "result", "message"):
            value = source.get(key)
            if isinstance(value, str):
                values.append(value[:2000])
    return "\n".join(values)


__all__ = ["HotPathResult", "successful_read_fast_path"]
