#!/usr/bin/env python3
"""Summarize workflow packet result files into an integration checklist."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


MARKERS = (
    "Accepted",
    "Rejected",
    "Conflict",
    "Decision",
    "Risk",
    "Verification",
    "TODO",
)


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def resolve_workspace_path(value: str, *, cwd: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute() or ".." in path.parts:
        raise argparse.ArgumentTypeError("path must stay inside the current workspace")
    resolved = (cwd / path).resolve()
    if not is_relative_to(resolved, cwd):
        raise argparse.ArgumentTypeError("path must stay inside the current workspace")
    return resolved


def resolve_child_path(path: Path, *, parent: Path, context: str) -> Path:
    if path.is_symlink():
        raise SystemExit(f"Refusing symlink {context}: {path}")
    try:
        resolved = path.resolve(strict=True)
        resolved_parent = parent.resolve(strict=True)
    except OSError as exc:
        raise SystemExit(f"Refusing unreadable {context}: {path}: {exc}") from exc
    if not is_relative_to(resolved, resolved_parent):
        raise SystemExit(f"Refusing {context} outside workflow: {path}")
    return resolved


def heading_for(path: Path) -> str:
    return path.stem.replace("-", " ").replace("_", " ").title()


def interesting_lines(text: str) -> list[str]:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if stripped.startswith(("-", "*", "#")) or any(marker.lower() in lowered for marker in MARKERS):
            lines.append(stripped)
    return lines[:40]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow_dir", help="Path to .workflow/<slug>")
    parser.add_argument(
        "--output",
        help="Optional output Markdown path (default: print to stdout)",
    )
    parser.add_argument("--force", action="store_true", help="Allow overwriting an existing regular output file.")
    args = parser.parse_args()

    cwd = Path.cwd().resolve()
    try:
        workflow_dir = resolve_workspace_path(args.workflow_dir, cwd=cwd)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    results_dir = workflow_dir / "results"
    if results_dir.is_symlink():
        raise SystemExit(f"Refusing symlink results directory: {results_dir}")
    if not results_dir.is_dir():
        raise SystemExit(f"Missing results directory: {results_dir}")
    results_dir = resolve_child_path(results_dir, parent=workflow_dir, context="results directory")

    files = sorted(results_dir.glob("*.md"))
    lines = [f"# Integration Checklist: {workflow_dir.name}", ""]
    if not files:
        lines.extend(["No result files found.", ""])
    for file in files:
        file = resolve_child_path(file, parent=results_dir, context="result file")
        text = file.read_text(encoding="utf-8")
        lines.extend([f"## {heading_for(file)}", ""])
        snippets = interesting_lines(text)
        if snippets:
            lines.extend(f"- untrusted result snippet: {html.escape(json.dumps(snippet), quote=True)}" for snippet in snippets)
        else:
            lines.append("No checklist-like lines found; inspect this result manually.")
        lines.append("")

    lines.extend(
        [
            "## Integration Decisions",
            "",
            "Accepted:",
            "",
            "Rejected:",
            "",
            "Conflicts:",
            "",
            "Remaining risks:",
            "",
            "Verification still needed:",
            "",
        ]
    )
    output = "\n".join(lines)
    if args.output:
        try:
            output_path = resolve_workspace_path(args.output, cwd=cwd)
        except argparse.ArgumentTypeError as exc:
            parser.error(str(exc))
        if output_path.exists() and (output_path.is_symlink() or not output_path.is_file()):
            raise SystemExit(f"Refusing to overwrite unsafe path: {output_path}")
        if output_path.exists() and not args.force:
            raise SystemExit(f"Refusing to overwrite existing output without --force: {output_path}")
        output_path.write_text(output, encoding="utf-8")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
