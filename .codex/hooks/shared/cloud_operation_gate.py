from __future__ import annotations

import shlex
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Literal

from shared.minikube_context import ContextVerification, verify_minikube_context
from shared.script_operation_inspector import script_cloud_commands, script_path, wrapper_script_path


CLOUD_TOOLS = {"aws", "gcloud", "helm", "kubectl", "minikube", "terraform"}
READ_ACTIONS = {
    "api-resources", "api-versions", "can-i", "cluster-info", "describe", "diff", "explain", "get",
    "get-contexts", "head", "history", "info", "list", "logs", "ls", "output", "plan", "providers",
    "search", "show", "status", "template", "top", "validate", "version", "view", "whoami",
}
DESTRUCTIVE_ACTIONS = {"delete", "destroy", "drain", "drop", "purge", "remove", "rm", "terminate", "uninstall", "wipe"}
MUTATING_ACTIONS = {
    "add", "annotate", "apply", "attach", "autoscale", "cordon", "cp", "create", "deploy", "detach",
    "edit", "expose", "import", "install", "label", "move", "mv", "patch", "put", "replace", "restart",
    "restore", "resume", "rollback", "rollout", "scale", "set", "start", "stop", "submit", "suspend",
    "taint", "uncordon", "update", "upgrade", "use-context",
}
COMPLETE_KUBERNETES_RESOURCES = {
    "cluster", "clusters", "crd", "customresourcedefinition", "customresourcedefinitions", "namespace",
    "namespaces", "node", "nodes", "ns",
}


@dataclass(frozen=True)
class CommandAssessment:
    action: Literal["allow", "approval", "block"]
    reason_code: str = ""
    reason: str = ""
    risk_level: str = ""
    tool: str = ""
    consequence: str = ""
    context: str = ""
    profile: str = ""
    warning: str = ""
    approval_subject: str = ""
ContextVerifier = Callable[[str], ContextVerification]
def _tool(value: str) -> str:
    return Path(value).name.lower()


def _segments(command: str) -> list[list[str]]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    segments: list[list[str]] = []
    current: list[str] = []
    for piece in lexer:
        if piece and all(char in ";&|" for char in piece):
            if current:
                segments.append(current)
                current = []
            continue
        current.append(piece)
    if current:
        segments.append(current)
    return segments


def _without_environment(parts: list[str]) -> list[str]:
    index = 1 if parts and _tool(parts[0]) == "env" else 0
    while index < len(parts) and "=" in parts[index] and not parts[index].startswith("-"):
        index += 1
    return parts[index:]


def _context(parts: list[str]) -> str:
    for index, part in enumerate(parts):
        if part == "--context" and index + 1 < len(parts):
            return parts[index + 1]
        if part.startswith("--context="):
            return part.split("=", 1)[1]
    return ""


def _option(parts: list[str], name: str) -> str:
    for index, part in enumerate(parts):
        if part == name and index + 1 < len(parts):
            return parts[index + 1]
        if part.startswith(name + "="):
            return part.split("=", 1)[1]
    return ""


def _words(parts: list[str]) -> list[str]:
    return [Path(part).name.lower().replace("_", "-") for part in parts[1:] if part and not part.startswith("-")]


def _kubectl_complete_deletion(parts: list[str]) -> bool:
    words = _words(parts)
    if "delete" not in words:
        return False
    operands = words[words.index("delete") + 1 :]
    return (
        "--all" in parts
        or "--all-namespaces" in parts
        or "-A" in parts
        or any(resource in COMPLETE_KUBERNETES_RESOURCES for resource in operands)
        or any(
            part in {"-f", "--filename", "-k", "--kustomize"}
            or part.startswith(("--filename=", "--kustomize="))
            for part in parts
        )
    )


def _classify_words(parts: list[str]) -> tuple[str, str]:
    words = _words(parts)
    if any(words[index : index + 2] == ["rollout", "status"] for index in range(len(words) - 1)):
        return ("read", "")
    destructive = next((word for word in words if any(word == action or word.startswith(action + "-") for action in DESTRUCTIVE_ACTIONS)), "")
    if destructive:
        return ("destructive", destructive)
    mutating = next((word for word in words if any(word == action or word.startswith(action + "-") for action in MUTATING_ACTIONS)), "")
    if mutating:
        return ("mutating", mutating)
    if any(word in READ_ACTIONS or word.startswith(("describe-", "get-", "list-", "head-")) for word in words):
        return ("read", "")
    return ("mutating", "unclassified")


def _shell_command(parts: list[str]) -> str:
    for index, part in enumerate(parts[1:], start=1):
        if part.startswith("-") and not part.startswith("--") and part[1:].isalpha() and "c" in part[1:]:
            return parts[index + 1] if index + 1 < len(parts) else ""
    return ""


def _approval(tool: str, risk: str, consequence: str) -> CommandAssessment:
    return CommandAssessment(
        action="approval",
        reason_code="cloud_command_approval_required",
        risk_level=risk,
        tool=tool,
        consequence=consequence,
    )


def _assess_cloud_parts(parts: list[str], verifier: ContextVerifier) -> CommandAssessment:
    tool = _tool(parts[0])
    risk, operation = _classify_words(parts)
    if tool != "kubectl":
        if risk == "read":
            return CommandAssessment(action="allow", tool=tool)
        return _approval(tool, risk, f"{operation} cluster or cloud state")

    context = _context(parts)
    if not context:
        return CommandAssessment(
            action="block",
            reason_code="kubectl_context_required",
            reason="Every kubectl command must declare --context explicitly.",
            tool=tool,
        )
    if any(char in context for char in "$`{}"):
        return CommandAssessment(
            action="block",
            reason_code="kubectl_context_not_static",
            reason="kubectl --context must be a static context name.",
            tool=tool,
        )
    verification = verifier(context)
    if not verification.valid:
        return CommandAssessment(
            action="block",
            reason_code="kubectl_context_invalid",
            reason="The declared kubectl context does not resolve to a configured cluster.",
            tool=tool,
            context=context,
        )
    complete = _kubectl_complete_deletion(parts)
    if verification.is_minikube and not complete:
        warning = "" if risk == "read" else f"verified minikube {context}: {operation} local resources"
        return CommandAssessment(
            action="allow",
            tool=tool,
            context=context,
            profile=verification.profile,
            warning=warning,
        )
    if risk == "read":
        return CommandAssessment(action="allow", tool=tool, context=context)
    consequence = "delete a complete Kubernetes scope" if complete else f"{operation} non-minikube cluster state"
    approval = _approval(tool, "destructive" if complete else risk, consequence)
    return replace(approval, context=context)


def _choose(assessments: list[CommandAssessment]) -> CommandAssessment:
    blocked = next((item for item in assessments if item.action == "block"), None)
    if blocked:
        return blocked
    approvals = [item for item in assessments if item.action == "approval"]
    if approvals:
        return next((item for item in approvals if item.risk_level == "destructive"), approvals[0])
    warning = next((item for item in assessments if item.warning), None)
    meaningful_allow = next((item for item in assessments if item.tool), None)
    return warning or meaningful_allow or CommandAssessment(action="allow")


def assess_command(
    command: str,
    cwd: Path,
    verifier: ContextVerifier = verify_minikube_context,
) -> CommandAssessment:
    script_hashes: list[str] = []
    assessments: list[CommandAssessment] = []
    try:
        segments = _segments(command)
    except ValueError:
        approval = _approval("command", "mutating", "execute a command that cannot be parsed safely")
        return replace(approval, approval_subject=command)

    def assess_parts(raw_parts: list[str], depth: int = 0) -> None:
        parts = _without_environment(raw_parts)
        if not parts:
            return
        if depth > 3:
            assessments.append(_approval("local-script", "mutating", "execute nested script logic beyond inspection depth"))
            return
        tool = _tool(parts[0])
        if tool in {"bash", "sh", "zsh"}:
            shell_command = _shell_command(parts)
            if shell_command:
                try:
                    for segment in _segments(shell_command):
                        assess_parts(segment, depth + 1)
                except ValueError:
                    assessments.append(_approval("local-script", "mutating", "execute dynamic shell content"))
                return
        if tool == "xargs":
            for index, part in enumerate(parts[1:], start=1):
                nested_tool = _tool(part)
                if nested_tool in CLOUD_TOOLS or nested_tool in {"bash", "sh", "zsh"} or script_path(parts[index:], cwd):
                    assess_parts(parts[index:], depth + 1)
                    return
            return
        trusted_wrapper = Path.home() / ".ralph-codex" / "bin" / "run-local-minikube-script"
        if tool in {"run-local-minikube-script", "run-local-minikube-script.py"}:
            if Path(parts[0]).expanduser() != trusted_wrapper:
                assessments.append(_approval("local-script", "mutating", "execute an unverified minikube wrapper"))
                return
            wrapper_context = _context(parts)
            wrapper_profile = _option(parts, "--profile")
            verification = verifier(wrapper_context) if wrapper_context else ContextVerification(False, False)
            if (
                not wrapper_context
                or not verification.valid
                or not verification.is_minikube
                or wrapper_profile != verification.profile
            ):
                assessments.append(
                    CommandAssessment(
                        action="block",
                        reason_code="minikube_wrapper_context_invalid",
                        reason=(
                            "The minikube runner requires matching --profile and --context values that resolve "
                            "to the same running minikube API endpoint."
                        ),
                        tool="local-script",
                        context=wrapper_context,
                    )
                )
                return
            script = wrapper_script_path(parts, cwd)
            if not script:
                assessments.append(
                    CommandAssessment(
                        action="block",
                        reason_code="local_script_invalid",
                        reason="The minikube runner requires a readable regular script file.",
                        tool="local-script",
                    )
                )
                return
            assessments.append(
                CommandAssessment(
                    action="allow",
                    tool="local-script",
                    context=wrapper_context,
                    profile=verification.profile,
                )
            )
        else:
            script = script_path(parts, cwd)

        if script:
            commands, error, script_hash = script_cloud_commands(script)
            if script_hash:
                script_hashes.append(f"{script}:{script_hash}")
            if error:
                assessments.append(_approval("local-script", "mutating", error))
                return
            for script_command in commands:
                try:
                    for segment in _segments(script_command):
                        assess_parts(segment, depth + 1)
                except ValueError:
                    assessments.append(
                        _approval("local-script", "mutating", "execute a cloud command that cannot be parsed statically")
                    )
            return

        if tool in CLOUD_TOOLS:
            assessments.append(_assess_cloud_parts(parts, verifier))

    for segment in segments:
        assess_parts(segment)
    chosen = _choose(assessments)
    subject = f"{cwd.resolve(strict=False)}\n{command}"
    if script_hashes:
        subject += "\n" + "\n".join(sorted(set(script_hashes)))
    return replace(chosen, approval_subject=subject)
