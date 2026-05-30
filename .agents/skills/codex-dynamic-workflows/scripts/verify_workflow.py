#!/usr/bin/env python3
"""Check that an AI-agent dynamic workflow artifact is complete enough to audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_FILES = ("plan.md", "state.json", "orchestration.md", "final-report.md")
REQUIRED_DIRS = ("packets", "results")


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow_dir", help="Path to .workflow/<slug>")
    parser.add_argument("--complete", action="store_true", help="Require at least one packet and one result file.")
    args = parser.parse_args()

    try:
        workflow_dir = resolve_workspace_path(args.workflow_dir, cwd=Path.cwd().resolve())
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    failures: list[str] = []

    if not workflow_dir.is_dir():
        failures.append(f"Missing workflow directory: {workflow_dir}")
    for name in REQUIRED_FILES:
        path = workflow_dir / name
        if path.is_symlink():
            failures.append(f"Symlink file is not allowed: {path}")
        elif not path.is_file():
            failures.append(f"Missing file: {path}")
        else:
            safe_path = resolve_child_path(path, parent=workflow_dir, context="required file")
            if not safe_path.read_text(encoding="utf-8").strip():
                failures.append(f"Empty file: {path}")
    for name in REQUIRED_DIRS:
        path = workflow_dir / name
        if path.is_symlink():
            failures.append(f"Symlink directory is not allowed: {path}")
        elif not path.is_dir():
            failures.append(f"Missing directory: {path}")
        else:
            resolve_child_path(path, parent=workflow_dir, context="required directory")

    state_path = workflow_dir / "state.json"
    if state_path.is_file() and not state_path.is_symlink():
        try:
            safe_state_path = resolve_child_path(state_path, parent=workflow_dir, context="state file")
            state = json.loads(safe_state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append(f"Invalid JSON in {state_path}: {exc}")
        else:
            for key in ("title", "slug", "status", "approval", "packets", "verification"):
                if key not in state:
                    failures.append(f"Missing state key: {key}")

    packets_dir = workflow_dir / "packets"
    results_dir = workflow_dir / "results"
    packet_files = sorted(packets_dir.glob("*.md")) if packets_dir.is_dir() and not packets_dir.is_symlink() else []
    result_files = sorted(results_dir.glob("*.md")) if results_dir.is_dir() and not results_dir.is_symlink() else []
    for file in packet_files:
        resolve_child_path(file, parent=packets_dir, context="packet file")
    for file in result_files:
        resolve_child_path(file, parent=results_dir, context="result file")
    if args.complete and not packet_files:
        failures.append("No packet files found under packets/")
    if args.complete and not result_files:
        failures.append("No result files found under results/")

    if failures:
        print("Workflow verification failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"Workflow verification passed: {workflow_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
