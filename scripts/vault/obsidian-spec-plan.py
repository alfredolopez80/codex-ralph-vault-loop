#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

from _vault_common import default_project, now_iso, parse_frontmatter, sanitize_slug, vault_dir, yaml_scalar


def body_without_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---", 4)
    if end == -1:
        return text
    return text[end + 4 :].lstrip()


def extract_section(body: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(body)
    if not match:
        return ""
    start = match.end()
    next_heading = re.search(r"^##\s+", body[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(body)
    return body[start:end].strip()


def render_plan(spec_path: Path, metadata: dict[str, str], body: str, project: str) -> str:
    title = metadata.get("title") or spec_path.stem
    classification = metadata.get("classification") or "YELLOW"
    first_line = body.splitlines()[0] if body.splitlines() else title
    objective = extract_section(body, "Objective") or first_line
    acceptance = extract_section(body, "Acceptance Criteria") or "Run the phase gates and record evidence."
    scope = extract_section(body, "Scope") or "Use the current spec note as the implementation boundary."
    source = str(spec_path)
    header = {
        "title": f"Plan - {title}",
        "classification": classification,
        "project": project,
        "kind": "obsidian-spec-plan",
        "source_spec": source,
        "dry_run": "true",
        "created_at": now_iso(),
    }
    lines = ["---"]
    lines.extend(f"{key}: {yaml_scalar(value)}" for key, value in header.items())
    lines.extend(
        [
            "---",
            "",
            f"# Plan - {title}",
            "",
            "## Objective",
            objective.strip(),
            "",
            "## Scope",
            scope.strip(),
            "",
            "## Acceptance Criteria",
            acceptance.strip(),
            "",
            "## Execution Plan",
            "1. Classify the spec and block RED content.",
            "2. Load only the vault note and repo files required by the scope.",
            "3. Invoke the orchestrator skill to decompose implementation tasks.",
            "4. Apply code changes only after a non-dry-run approval path is selected.",
            "5. Run gates, capture results, and write a handoff note.",
            "",
            "## Dry Run Result",
            "No repository code was modified by this plan generator.",
            "",
        ]
    )
    return "\n".join(lines)


def default_output_path(spec_path: Path, project: str) -> Path:
    return vault_dir() / "projects" / sanitize_slug(project) / "handoffs" / f"{sanitize_slug(spec_path.stem)}-plan.md"


def append_spec_status(spec_path: Path, plan_path: Path) -> None:
    marker = f"\n\n## Ralph Plan\n\nPlan generated: `{plan_path}`\n"
    text = spec_path.read_text(encoding="utf-8")
    if "## Ralph Plan" not in text:
        spec_path.write_text(text.rstrip() + marker, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an implementation plan from an Obsidian spec note without editing repo code.")
    parser.add_argument("--spec", required=True, help="Path to a spec Markdown note inside the vault.")
    parser.add_argument("--project", default=default_project())
    parser.add_argument("--output")
    parser.add_argument("--update-spec", action="store_true", help="Append the generated plan path to the spec note.")
    args = parser.parse_args()

    spec_path = Path(args.spec).expanduser().resolve()
    if not spec_path.exists():
        print(f"OBSIDIAN_SPEC_PLAN_MISSING {spec_path}")
        return 1

    raw = spec_path.read_text(encoding="utf-8")
    metadata = parse_frontmatter(raw)
    classification = (metadata.get("classification") or "YELLOW").upper()
    if classification == "RED":
        print(f"OBSIDIAN_SPEC_PLAN_BLOCKED_RED {spec_path}")
        return 2

    output = Path(args.output).expanduser().resolve() if args.output else default_output_path(spec_path, args.project)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_plan(spec_path, metadata, body_without_frontmatter(raw), args.project), encoding="utf-8")
    if args.update_spec:
        append_spec_status(spec_path, output)
    print(f"OBSIDIAN_SPEC_PLAN_OK {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
