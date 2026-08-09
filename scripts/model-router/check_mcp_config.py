#!/usr/bin/env python3
"""Offline MCP configuration audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SECURITY_DIR = Path(__file__).resolve().parents[1] / "security"
if str(SECURITY_DIR) not in sys.path:
    sys.path.insert(0, str(SECURITY_DIR))
from sensitive_content import classify_text


CANONICAL_SERVERS = {
    "zai_web_search",
    "zai_web_reader",
    "zai_zread",
    "zai_vision",
    "minimax_coding_tools",
    "ralph_coding_models",
}
LEGACY_ALIASES = {
    "web-search-prime": "zai_web_search",
    "web-reader": "zai_web_reader",
    "zread": "zai_zread",
}


@dataclass(frozen=True)
class ServerRecord:
    name: str
    active: bool
    endpoint: tuple[Any, ...]
    tools: tuple[str, ...]


def _active(value: dict[str, Any]) -> bool:
    return value.get("enabled") is not False and value.get("disabled") is not True


def _endpoint(value: dict[str, Any]) -> tuple[Any, ...]:
    if "url" in value:
        return ("http", str(value.get("url", "")))
    return (
        "stdio",
        str(value.get("command", "")),
        tuple(str(item) for item in value.get("args", []) or []),
        str(value.get("cwd", "")),
        tuple(sorted(str(item) for item in value.get("env_vars", []) or [])),
    )


def load_config(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    if not isinstance(data.get("mcp_servers"), dict):
        raise ValueError("mcp_servers must be a TOML table")
    return data


def inspect_config(data: dict[str, Any]) -> dict[str, Any]:
    raw_servers = data.get("mcp_servers", {})
    records: list[ServerRecord] = []
    errors: list[str] = []
    warnings: list[str] = []
    for name, raw in raw_servers.items():
        if not isinstance(raw, dict):
            errors.append(f"server {name} is not a table")
            continue
        tools = raw.get("enabled_tools", [])
        valid_tools = isinstance(tools, list) and all(isinstance(item, str) and item for item in tools)
        normalized_tools = tuple(tools) if valid_tools else ()
        if not valid_tools:
            errors.append(f"server {name} has invalid enabled_tools")
        if len(set(normalized_tools)) != len(normalized_tools):
            errors.append(f"server {name} repeats an enabled tool")
        if name in LEGACY_ALIASES and _active(raw):
            errors.append(f"legacy alias is active: {name}")
        if name not in CANONICAL_SERVERS and name not in LEGACY_ALIASES:
            if _active(raw):
                errors.append(f"noncanonical active server name: {name}")
            else:
                warnings.append(f"unclassified disabled server name: {name}")
        records.append(ServerRecord(name, _active(raw), _endpoint(raw), normalized_tools))

    active = [record for record in records if record.active]
    endpoint_groups: dict[tuple[Any, ...], list[str]] = {}
    schema_groups: dict[tuple[Any, ...], list[str]] = {}
    for record in active:
        endpoint_groups.setdefault(record.endpoint, []).append(record.name)
        for tool in record.tools:
            schema_groups.setdefault((record.endpoint, tool), []).append(f"{record.name}.{tool}")
    for names in endpoint_groups.values():
        if len(names) > 1:
            errors.append(f"duplicate active endpoint: {','.join(sorted(names))}")
    for names in schema_groups.values():
        if len(names) > 1:
            errors.append(f"duplicate active tool schema: {','.join(sorted(names))}")
    if classify_text(json.dumps(data, ensure_ascii=True, sort_keys=True)).classification == "RED":
        errors.append("config contains classified material")

    return {
        "schema_version": "mcp-config-audit-v1",
        "active_server_count": len(active),
        "configured_server_count": len(records),
        "enabled_tool_count": sum(len(record.tools) for record in active),
        "enabled_tool_unique_count": len({(record.name, tool) for record in active for tool in record.tools}),
        "estimated_schema_count": len(schema_groups),
        "duplicate_endpoint_count": sum(1 for names in endpoint_groups.values() if len(names) > 1),
        "duplicate_schema_count": sum(1 for names in schema_groups.values() if len(names) > 1),
        "active_legacy_aliases": sorted(record.name for record in active if record.name in LEGACY_ALIASES),
        "server_names": sorted(record.name for record in active),
        "server_tools": {record.name: list(record.tools) for record in active},
        "server_endpoint_hashes": {
            record.name: hashlib.sha256(repr(record.endpoint).encode("utf-8")).hexdigest() for record in active
        },
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "startup_ms": None,
    }


def check_migration_doc(path: Path) -> list[str]:
    if not path.is_file():
        return [f"migration document missing: {path}"]
    text = path.read_text(encoding="utf-8")
    names = tuple(LEGACY_ALIASES)
    return [f"migration document missing legacy name: {name}" for name in names if name not in text]


def compare_reports(reports: list[dict[str, Any]]) -> list[str]:
    if not reports:
        return []
    first = reports[0]
    errors: list[str] = []
    for report in reports[1:]:
        if report["server_names"] != first["server_names"]:
            errors.append("project/global active server names differ")
        if report["enabled_tool_count"] != first["enabled_tool_count"]:
            errors.append("project/global enabled tool counts differ")
        if report["server_tools"] != first["server_tools"]:
            errors.append("project/global enabled tool sets differ")
        if report["server_endpoint_hashes"] != first["server_endpoint_hashes"]:
            errors.append("project/global endpoint identities differ")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", action="append", required=True, type=Path)
    parser.add_argument("--migration-doc", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    reports: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in args.config:
        try:
            report = {"config": str(path), **inspect_config(load_config(path))}
            reports.append(report)
            errors.extend(report["errors"])
        except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
            errors.append(f"{path}: {exc}")
    errors.extend(compare_reports(reports))
    if args.migration_doc:
        errors.extend(check_migration_doc(args.migration_doc))
    payload = {"schema_version": "mcp-config-audit-v1", "reports": reports, "errors": sorted(set(errors))}
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=True, sort_keys=True))
    elif errors:
        for error in sorted(set(errors)):
            print(f"MCP_CONFIG_FAIL {error}", file=sys.stderr)
    else:
        for report in reports:
            print(
                "MCP_CONFIG_OK "
                f"config={report['config']} servers={report['active_server_count']} "
                f"enabled_tools={report['enabled_tool_count']} schemas={report['estimated_schema_count']}"
            )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
