"""Resolve the effective hook graph and its semantic blocking owners.

The Codex hook matcher does not treat project precedence as suppression: a
global hook and a project hook can both run.  This module therefore compares
the effective command graph, normalizes dispatcher roles, and reports one
blocking semantic owner per v4 domain.  It is deliberately side-effect free;
the CLI wrapper is responsible for loading configuration snapshots.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


DOMAINS: tuple[str, ...] = (
    "prompt_boundary",
    "pre_tool_safety",
    "post_tool_persistence",
    "stop_completion",
)

BLOCKING_ROLES: dict[str, frozenset[str]] = {
    "prompt_boundary": frozenset({"user_prompt_dispatch", "universal_prompt_classifier"}),
    "pre_tool_safety": frozenset({"pre_tool_dispatch", "pre_tool_guard"}),
    "post_tool_persistence": frozenset({"post_tool_dispatch", "post_tool_checkpoint", "post_tool_extract_memory"}),
    "stop_completion": frozenset({"stop_dispatch", "ralph_stop_quality_gate", "anti_rationalization_stop"}),
}
REPORT_ONLY_ROLES: dict[str, frozenset[str]] = {
    "prompt_boundary": frozenset({"user_prompt_capture", "user_prompt_improve", "continuity_prompt_context"}),
    "pre_tool_safety": frozenset({"subagent_routing_pretool_guard", "sol_advisor_pretool_guard"}),
    "post_tool_persistence": frozenset({"post_tool_cost_ledger", "shaping_ripple", "sol_advisor_observer"}),
    "stop_completion": frozenset({"stop_route_decision_warn", "implementation_notes_guard", "sol_advisor_stop_guard", "stop_persist_memory", "stop_memory_promotion_review", "file_line_guard_stop"}),
}
ROLE_RE = re.compile(r"global_hook_dispatch\.py\s+--event\s+\S+\s+--role\s+([A-Za-z0-9_-]+)")
FILE_RE = re.compile(r"([A-Za-z0-9_.-]+\.(?:py|sh))")


@dataclass(frozen=True)
class HookEntry:
    event: str
    role: str
    source: str
    command: str
    blocking: bool
    domain: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DomainResult:
    domain: str
    blocking_owners: tuple[str, ...]
    report_only_roles: tuple[str, ...]
    status: str
    evidence: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HookGraphReport:
    status: str
    domains: tuple[DomainResult, ...]
    entries: tuple[HookEntry, ...]
    legacy_wrapper_registered: bool
    warnings: tuple[str, ...]
    errors: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "domains": [item.as_dict() for item in self.domains],
            "entries": [item.as_dict() for item in self.entries],
            "legacy_wrapper_registered": self.legacy_wrapper_registered,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


def analyze_hook_graph(configs: Iterable[tuple[str, Mapping[str, Any]]]) -> HookGraphReport:
    entries: list[HookEntry] = []
    warnings: list[str] = []
    errors: list[str] = []
    legacy_registered = False
    for source, config in configs:
        if not isinstance(config, Mapping):
            errors.append(f"{source}: configuration is not an object")
            continue
        hooks = config.get("hooks")
        if not isinstance(hooks, Mapping):
            errors.append(f"{source}: hooks table is missing")
            continue
        for event, groups in hooks.items():
            if not isinstance(event, str) or not isinstance(groups, list):
                errors.append(f"{source}: invalid hook event table")
                continue
            for group in groups:
                if not isinstance(group, Mapping):
                    errors.append(f"{source}:{event}: hook group is not an object")
                    continue
                children = group.get("hooks")
                if not isinstance(children, list):
                    errors.append(f"{source}:{event}: hook group has no hooks array")
                    continue
                for child in children:
                    if not isinstance(child, Mapping):
                        errors.append(f"{source}:{event}: hook entry is not an object")
                        continue
                    command = str(child.get("command") or "")
                    role = role_for_command(command)
                    if not role:
                        warnings.append(f"{source}:{event}: unclassified command")
                        continue
                    if source.startswith("plugin:") and domain_for_role(role) is None:
                        warnings.append(f"{source}:{event}: plugin hook is unclassified report-only")
                    if role == "anti_rationalization_stop":
                        legacy_registered = True
                    domain = domain_for_role(role)
                    blocking = domain is not None and role in set().union(*BLOCKING_ROLES.values())
                    entries.append(HookEntry(event, role, source, command, blocking, domain))

    domains: list[DomainResult] = []
    for domain in DOMAINS:
        blocking = sorted({entry.role for entry in entries if entry.domain == domain and entry.blocking})
        report_only = sorted({entry.role for entry in entries if entry.domain == domain and not entry.blocking})
        evidence = tuple(f"{entry.source}:{entry.event}:{entry.role}" for entry in entries if entry.domain == domain)
        if len(blocking) == 1:
            status = "PASS"
        elif len(blocking) == 0:
            status = "FAIL"
            errors.append(f"{domain}: no blocking semantic owner")
        else:
            status = "FAIL"
            errors.append(f"{domain}: duplicate blocking owners {','.join(blocking)}")
        if report_only:
            warnings.append(f"{domain}: report-only roles {','.join(report_only)}")
        domains.append(DomainResult(domain, tuple(blocking), tuple(report_only), status, evidence))
    if legacy_registered:
        errors.append("legacy anti-rationalization-stop.sh is registered")
    status = "FAIL" if errors else "WARN" if warnings else "PASS"
    return HookGraphReport(status, tuple(domains), tuple(entries), legacy_registered, tuple(sorted(set(warnings))), tuple(sorted(set(errors))))


def role_for_command(command: str) -> str:
    if not isinstance(command, str):
        return ""
    match = ROLE_RE.search(command)
    if match:
        return match.group(1)
    basename = ""
    matches = list(FILE_RE.finditer(command))
    if matches:
        basename = matches[-1].group(1)
    else:
        basename = command.rsplit("/", 1)[-1].split()[0] if command.strip() else ""
    aliases = {
        "universal-prompt-classifier.sh": "universal_prompt_classifier",
        "anti-rationalization-stop.sh": "anti_rationalization_stop",
        "ralph-stop-quality-gate.sh": "ralph_stop_quality_gate",
    }
    if basename in aliases:
        return aliases[basename]
    return basename.removesuffix(".py").replace("-", "_")


def domain_for_role(role: str) -> str | None:
    for domain, roles in BLOCKING_ROLES.items():
        if role in roles:
            return domain
    for domain, roles in REPORT_ONLY_ROLES.items():
        if role in roles:
            return domain
    return None


__all__ = ["DOMAINS", "DomainResult", "HookEntry", "HookGraphReport", "analyze_hook_graph", "domain_for_role", "role_for_command"]
