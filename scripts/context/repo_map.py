#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from .context_common import iter_repo_files, markdown_list, relative, write_json, write_output
except ImportError:  # pragma: no cover - direct script execution
    from context_common import iter_repo_files, markdown_list, relative, write_json, write_output


SURFACE_LIMIT = 20


def surface_bucket(path: Path, rel_path: str) -> str | None:
    parts = Path(rel_path).parts
    name = path.name
    suffix = path.suffix.lower()
    if parts[:2] == (".codex", "hooks") or rel_path == ".codex/hooks.json":
        return "hook_surfaces"
    if parts[:2] == (".codex", "tests"):
        return "test_surfaces"
    if parts and parts[0] == "tests" or name.startswith("test_"):
        return "test_surfaces"
    if parts and parts[0] == "docs" or name in {"README.md", "AGENTS.md"}:
        return "docs_surfaces"
    if name in {"AGENTS.md", "README.md", "pyproject.toml"} or parts[:1] == ("scripts",):
        return "entry_points"
    if suffix in {".json", ".toml", ".yaml", ".yml"} or parts[:1] in {("config",), (".codex",)}:
        return "config_surfaces"
    return None


def likely_validation_commands(root: Path) -> list[str]:
    commands: list[str] = []
    if (root / "scripts" / "setup" / "doctor.sh").exists():
        commands.append("bash scripts/setup/doctor.sh")
    if (root / "scripts" / "gates" / "run-gates.py").exists():
        commands.append("python3 scripts/gates/run-gates.py --minimal")
    if (root / "tests").exists():
        commands.append("PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q")
    if (root / "scripts" / "validate-ralph-memory-flow.sh").exists():
        commands.append("bash scripts/validate-ralph-memory-flow.sh")
    if (root / "scripts" / "evals" / "coding_model_eval.py").exists():
        commands.append("python3 scripts/evals/coding_model_eval.py --mode mock")
    return commands


def surface_candidates(root: Path, max_depth: int) -> list[Path]:
    candidates: dict[str, Path] = {}
    for base in [root, root / "scripts", root / ".codex", root / "tests", root / "docs", root / "config"]:
        if not base.exists():
            continue
        for path in iter_repo_files(base, max_files=500, max_depth=max_depth):
            candidates[relative(path, root)] = path
    return [candidates[key] for key in sorted(candidates)]


def build_map(root: Path, max_files: int, max_depth: int) -> dict[str, Any]:
    root = root.expanduser().resolve()
    files = iter_repo_files(root, max_files=max_files, max_depth=max_depth)
    surfaces: dict[str, list[str]] = {
        "entry_points": [],
        "config_surfaces": [],
        "hook_surfaces": [],
        "test_surfaces": [],
        "docs_surfaces": [],
    }
    top_dirs: Counter[str] = Counter()
    suffixes: Counter[str] = Counter()
    for path in files:
        rel_path = relative(path, root)
        parts = Path(rel_path).parts
        top_dirs[parts[0] if len(parts) > 1 else "."] += 1
        suffixes[path.suffix.lower() or "<none>"] += 1
    for path in surface_candidates(root, max_depth):
        rel_path = relative(path, root)
        bucket = surface_bucket(path, rel_path)
        if bucket and len(surfaces[bucket]) < SURFACE_LIMIT:
            surfaces[bucket].append(rel_path)
    for key, values in surfaces.items():
        surfaces[key] = sorted(values)
    return {
        "root": str(root),
        "max_depth": max_depth,
        "file_count_sampled": len(files),
        "truncated": len(files) >= max_files,
        "top_dirs": dict(sorted(top_dirs.items(), key=lambda item: (-item[1], item[0]))[:20]),
        "suffixes": dict(sorted(suffixes.items(), key=lambda item: (-item[1], item[0]))[:20]),
        "surfaces": surfaces,
        "likely_validation_commands": likely_validation_commands(root),
    }


def render_markdown(report: dict[str, Any]) -> str:
    surfaces = report["surfaces"]
    lines = [
        "# Compact Repo Map",
        "",
        f"- Root: `{report['root']}`",
        f"- Sampled files: `{report['file_count_sampled']}`",
        f"- Max depth: `{report['max_depth']}`",
        f"- Truncated: `{'yes' if report['truncated'] else 'no'}`",
        "",
        "## Entry Points",
        markdown_list(surfaces["entry_points"]),
        "",
        "## Config Surfaces",
        markdown_list(surfaces["config_surfaces"]),
        "",
        "## Hook Surfaces",
        markdown_list(surfaces["hook_surfaces"]),
        "",
        "## Test Surfaces",
        markdown_list(surfaces["test_surfaces"]),
        "",
        "## Docs Surfaces",
        markdown_list(surfaces["docs_surfaces"]),
        "",
        "## Top Directories",
        "\n".join(f"- `{name}`: {count}" for name, count in report["top_dirs"].items()) or "- none",
        "",
        "## Likely Validation Commands",
        markdown_list(report["likely_validation_commands"]),
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a concise deterministic repository overview.")
    parser.add_argument("--root", default=".", help="Repository root to scan.")
    parser.add_argument("--max-files", type=int, default=250, help="Maximum files to sample before stopping.")
    parser.add_argument("--max-depth", type=int, default=4, help="Maximum directory depth to inspect.")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format.")
    parser.add_argument("--output", help="Optional output path. Defaults to stdout.")
    args = parser.parse_args(argv)

    report = build_map(Path(args.root), args.max_files, args.max_depth)
    if args.format == "json":
        write_json(report, args.output)
    else:
        write_output(render_markdown(report), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
