"""Resolve the effective hook graph and its semantic blocking owners.

The Codex hook matcher does not treat project precedence as suppression: a
global hook and a project hook can both run.  This module therefore compares
the effective command graph, normalizes dispatcher roles, and reports one
blocking semantic owner per v4 domain.  It is deliberately side-effect free;
the CLI wrapper is responsible for loading configuration snapshots.
"""
from __future__ import annotations

import hashlib
import json
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
REQUIRED_EVENTS: dict[str, str] = {
    "prompt_boundary": "UserPromptSubmit",
    "pre_tool_safety": "PreToolUse",
    "post_tool_persistence": "PostToolUse",
    "stop_completion": "Stop",
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


def analyze_hook_graph(
    configs: Iterable[tuple[str, Mapping[str, Any]]],
    *,
    trusted_report_only: Mapping[str, Mapping[str, str]] | None = None,
) -> HookGraphReport:
    """Resolve ownership, failing closed on unknown guarded plugin hooks.

    A narrow matcher is not evidence that an unknown plugin hook is
    report-only: it can still block, close, or mutate when its event fires.
    The only exception is an explicit, version-controlled declaration digest
    supplied by the doctor.  This keeps plugin trust data separate from the
    untrusted manifest being inspected and makes a hook change fail closed.
    """

    trusted_report_only = trusted_report_only or {}
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
                        message = f"{source}:{event}: unclassified command"
                        trusted_domain = _trusted_report_only_domain(
                            trusted_report_only,
                            source,
                            event,
                            group.get("matcher"),
                            command,
                            config.get("_ralph_verified_bundle"),
                        )
                        if trusted_domain is not None:
                            entries.append(HookEntry(event, "plugin_report_only", source, command, False, trusted_domain))
                            warnings.append(message + f" trusted report-only digest for {trusted_domain}")
                            continue
                        elif source.startswith("plugin:") and event in set(REQUIRED_EVENTS.values()):
                            errors.append(message + " may own a guarded domain; explicit trusted classification is required")
                        else:
                            warnings.append(message)
                        continue
                    if source.startswith("plugin:") and domain_for_role(role) is None:
                        message = f"{source}:{event}: plugin hook is unclassified"
                        trusted_domain = _trusted_report_only_domain(
                            trusted_report_only,
                            source,
                            event,
                            group.get("matcher"),
                            command,
                            config.get("_ralph_verified_bundle"),
                        )
                        if trusted_domain is not None:
                            entries.append(HookEntry(event, "plugin_report_only", source, command, False, trusted_domain))
                            warnings.append(message + f" trusted report-only digest for {trusted_domain}")
                            continue
                        elif event in set(REQUIRED_EVENTS.values()):
                            errors.append(message + " may own a guarded domain; explicit trusted classification is required")
                        else:
                            warnings.append(message)
                    if role == "anti_rationalization_stop":
                        legacy_registered = True
                    domain = domain_for_role(role)
                    if domain is not None and REQUIRED_EVENTS[domain] != event:
                        errors.append(
                            f"{source}:{event}:{role} is registered under {event}; "
                            f"{domain} requires {REQUIRED_EVENTS[domain]}"
                        )
                        continue
                    blocking = domain is not None and role in set().union(*BLOCKING_ROLES.values())
                    entries.append(HookEntry(event, role, source, command, blocking, domain))

    domains: list[DomainResult] = []
    for domain in DOMAINS:
        blocking_entries = sorted(
            (
                entry
                for entry in entries
                if entry.domain == domain
                and entry.blocking
                and not _suppressed_global_registration(entry, entries)
            ),
            key=lambda entry: (entry.source, entry.event, entry.role, entry.command),
        )
        # Ownership is a property of registrations, not distinct role names.
        # A project and global registration of the same dispatcher still run
        # twice and therefore constitute two blocking owners.
        blocking = [entry.role for entry in blocking_entries]
        report_only = sorted({entry.role for entry in entries if entry.domain == domain and not entry.blocking})
        evidence = tuple(f"{entry.source}:{entry.event}:{entry.role}" for entry in entries if entry.domain == domain)
        if len(blocking) == 1:
            status = "PASS"
        elif len(blocking) == 0:
            status = "FAIL"
            errors.append(f"{domain}: no blocking semantic owner")
        else:
            status = "FAIL"
            registrations = ",".join(
                f"{entry.source}:{entry.event}:{entry.role}" for entry in blocking_entries
            )
            errors.append(f"{domain}: duplicate blocking registrations {registrations}")
        if report_only:
            warnings.append(f"{domain}: report-only roles {','.join(report_only)}")
        domains.append(DomainResult(domain, tuple(blocking), tuple(report_only), status, evidence))
    if legacy_registered:
        errors.append("legacy anti-rationalization-stop.sh is registered")
    status = "FAIL" if errors else "WARN" if warnings else "PASS"
    return HookGraphReport(status, tuple(domains), tuple(entries), legacy_registered, tuple(sorted(set(warnings))), tuple(sorted(set(errors))))


def _suppressed_global_registration(entry: HookEntry, entries: list[HookEntry]) -> bool:
    """Exclude only the known global wrapper suppressed by a project owner.

    The global dispatcher checks whether the project already owns the same
    semantic role before invoking its child. This is different from two direct
    registrations, which remain a blocking duplicate and must fail closed.
    """

    if entry.source != "global" or "global_hook_dispatch.py" not in entry.command:
        return False
    return any(
        other is not entry
        and other.source == "project"
        and other.event == entry.event
        and other.role == entry.role
        and other.blocking
        for other in entries
    )


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


def _trusted_report_only_domain(
    trusted: Mapping[str, Mapping[str, str]],
    source: str,
    event: str,
    matcher: object,
    command: str,
    verified_bundle: object,
) -> str | None:
    if not source.startswith("plugin:") or not isinstance(matcher, str):
        return None
    declaration = {
        "source": source,
        "event": event,
        "matcher": matcher,
        "command": command,
    }
    if isinstance(verified_bundle, Mapping):
        declaration["bundle"] = dict(verified_bundle)
    digest = "sha256:" + hashlib.sha256(json.dumps(declaration, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    domain = trusted.get(source, {}).get(digest)
    if domain not in DOMAINS or REQUIRED_EVENTS.get(domain) != event:
        return None
    return domain


__all__ = ["DOMAINS", "DomainResult", "HookEntry", "HookGraphReport", "analyze_hook_graph", "domain_for_role", "role_for_command"]
