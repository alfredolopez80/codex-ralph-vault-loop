#!/usr/bin/env python3
"""Create an AI-agent dynamic workflow artifact directory."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:64].strip("-") or "workflow"


def workspace_relative_path(value: str, *, cwd: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute() or ".." in path.parts:
        raise argparse.ArgumentTypeError("path must stay inside the current workspace")
    resolved = (cwd / path).resolve()
    if not is_relative_to(resolved, cwd):
        raise argparse.ArgumentTypeError("path must stay inside the current workspace")
    return resolved


def write_new(path: Path, content: str) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise SystemExit(f"Refusing to reuse unsafe path: {path}")
        return
    with path.open("x", encoding="utf-8") as file:
        file.write(content)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("title", help="Workflow title or task summary")
    parser.add_argument(
        "--root",
        default=".workflow",
        help="Directory where workflow runs are stored (default: .workflow)",
    )
    parser.add_argument("--slug", help="Optional explicit workflow slug")
    args = parser.parse_args()

    cwd = Path.cwd().resolve()
    slug = slugify(args.slug or args.title)
    try:
        root = workspace_relative_path(args.root, cwd=cwd)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    run_dir = (root / slug).resolve()
    if not is_relative_to(run_dir, cwd):
        raise SystemExit(f"Refusing to write outside workspace: {run_dir}")
    if run_dir.exists():
        raise SystemExit(f"Refusing to reuse existing workflow directory: {run_dir}")
    packets_dir = run_dir / "packets"
    results_dir = run_dir / "results"
    packets_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    state = {
        "title": args.title,
        "slug": slug,
        "created_at": now,
        "status": "planned",
        "approval": {"required": None, "granted": None, "notes": ""},
        "packets": [],
        "verification": {"status": "not_started", "checks": []},
    }

    write_new(
        run_dir / "plan.md",
        f"""# {args.title}

## Goal

## Success Criteria

## Current Context

## Constraints

## Risks

## Approval Required

## Work Packets

## Integration Policy

## Verification

## Reusable Artifacts
""",
    )
    write_new(
        run_dir / "orchestration.md",
        f"""# Orchestration: {args.title}

## Execution Rules

- Keep the original objective intact.
- Ask for approval before risky, expensive, external, or destructive actions.
- Keep immediate blocking work local.
- Delegate only bounded, disjoint, materially useful packets.
- Integrate packet results before final verification.

## Branching Rules

## Packet Prompts

## Completion Audit
""",
    )
    write_new(run_dir / "state.json", json.dumps(state, indent=2) + "\n")
    write_new(
        run_dir / "final-report.md",
        f"""# Final Report: {args.title}

## Outcome

## Accepted Results

## Rejected Results

## Conflicts Resolved

## Verification Evidence

## Remaining Risks

## Reusable Follow-up
""",
    )

    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
