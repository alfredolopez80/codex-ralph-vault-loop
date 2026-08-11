#!/usr/bin/env python3
"""Report-only effective hook ownership doctor for Ralph v4."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.effective_hook_graph import analyze_hook_graph  # noqa: E402


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _enabled_plugin_keys(config_path: Path | None = None) -> tuple[str, ...]:
    """Return enabled plugin identities from the effective Codex config.

    The cache contains more manifests than the runtime has enabled.  Treating
    every cached file as effective produces false blockers for stale plugins;
    conversely, a shallow scan misses the versioned cache layout used by the
    runtime.  This resolver is deliberately read-only and bounded to the
    config plus the managed cache root.
    """

    path = config_path or (Path.home() / ".codex" / "config.toml")
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return ()
    plugins = document.get("plugins")
    if not isinstance(plugins, dict):
        return ()
    enabled: list[str] = []
    for identity, value in plugins.items():
        if isinstance(identity, str) and isinstance(value, dict) and value.get("enabled") is True:
            enabled.append(identity)
    return tuple(sorted(set(enabled)))


def _managed_plugin_manifests(root: Path, identity: str) -> tuple[Path, ...]:
    """Resolve active versioned manifests for ``name@marketplace``."""

    if "@" not in identity:
        return ()
    name, marketplace = identity.split("@", 1)
    if not name or not marketplace:
        return ()
    candidates: list[Path] = []
    cache_parent = root / "cache" / marketplace / name
    try:
        if cache_parent.is_dir():
            candidates.extend(sorted(cache_parent.glob("*/hooks.json")))
        # Some older installations keep the marketplace/name tree directly
        # under the plugin root.  Only the configured identity is eligible.
        legacy_parent = root / marketplace / name
        if legacy_parent.is_dir():
            candidates.extend(sorted(legacy_parent.glob("*/hooks.json")))
    except OSError:
        return ()
    return tuple(candidates[:32])


def installer_snapshot() -> dict[str, Any] | None:
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "setup" / "install-global-hooks.py"), "--dry-run", "--allow-worktree-source"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    start = result.stdout.find("{")
    if result.returncode != 0 or start < 0:
        return None
    try:
        value = json.loads(result.stdout[start:])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def plugin_snapshots() -> list[tuple[str, dict[str, Any]]]:
    """Load installed plugin hook manifests into the effective graph.

    Plugin hooks are additive in the Codex runtime, so project/global
    precedence alone cannot prove ownership.  Discovery is bounded to the
    configured plugin roots and the two managed local plugin roots; malformed
    manifests are surfaced as graph inputs and fail classification rather than
    being silently ignored.
    """

    roots: list[Path] = []
    configured = os.environ.get("CODEX_PLUGIN_ROOTS", "")
    for raw in configured.split(os.pathsep):
        if raw.strip():
            roots.append(Path(raw).expanduser())
    managed_root = Path.home() / ".codex" / "plugins"
    enabled = _enabled_plugin_keys()
    snapshots: list[tuple[str, dict[str, Any]]] = []
    seen: set[Path] = set()
    # The managed cache is filtered by the effective enabled-plugin table;
    # stale .tmp bundles and disabled versions never become hook owners.
    for identity in enabled:
        for path in _managed_plugin_manifests(managed_root, identity):
            try:
                resolved = path.resolve()
                if resolved in seen or not resolved.is_file() or resolved.stat().st_size > 256 * 1024:
                    continue
                seen.add(resolved)
                value = load_json(resolved)
            except OSError:
                value = None
            snapshots.append((f"plugin:{identity}", value or {"hooks": {}}))
    for root in roots:
        try:
            resolved_root = root.resolve()
            # Explicit test/diagnostic roots are allowed to enumerate their
            # bounded manifests.  They are caller-scoped and therefore do not
            # change production discovery of the managed cache.
            candidates = sorted(resolved_root.rglob("hooks.json"))[:256] if resolved_root.is_dir() else []
        except OSError:
            continue
        for path in candidates[:256]:
            try:
                resolved = path.resolve()
                if resolved in seen or not resolved.is_file() or resolved.stat().st_size > 256 * 1024:
                    continue
                seen.add(resolved)
                value = load_json(resolved)
            except OSError:
                value = None
            name = path.parent.name or "unknown"
            if value is None:
                snapshots.append((f"plugin:{name}", {"hooks": {}}))
            else:
                snapshots.append((f"plugin:{name}", value))
    return snapshots


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=ROOT / ".codex" / "hooks.json")
    parser.add_argument("--global-config", type=Path, default=None)
    parser.add_argument("--no-installer-snapshot", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    configs: list[tuple[str, dict[str, Any]]] = []
    project = load_json(args.project)
    if project is not None:
        configs.append(("project", project))
    global_path = args.global_config or (Path.home() / ".codex" / "hooks.json")
    global_config = load_json(global_path)
    if global_config is not None:
        configs.append(("global", global_config))
    if not args.no_installer_snapshot and global_config is None:
        generated = installer_snapshot()
        if generated is not None:
            configs.append(("global-dry-run", generated))
    configs.extend(plugin_snapshots())
    report = analyze_hook_graph(configs)
    payload = report.as_dict()
    payload["project_config"] = str(args.project)
    payload["global_config"] = str(global_path)
    payload["sources"] = [source for source, _ in configs]
    if args.json:
        print(json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2))
    else:
        print(f"EFFECTIVE_HOOK_GRAPH_{report.status}")
        for item in report.domains:
            print(f"{item.domain}: {item.status} owner={','.join(item.blocking_owners) or '-'}")
        for message in report.warnings:
            print(f"WARN {message}")
        for message in report.errors:
            print(f"FAIL {message}")
    return 0 if report.status in {"PASS", "WARN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
