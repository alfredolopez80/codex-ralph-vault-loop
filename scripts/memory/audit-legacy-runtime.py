#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _memory_common import content_hash, ralph_home


REPO_ROOT = Path(__file__).resolve().parents[2]
SECURITY_DIR = REPO_ROOT / "scripts" / "security"
if str(SECURITY_DIR) not in sys.path:
    sys.path.insert(0, str(SECURITY_DIR))

from sensitive_content import public_findings  # noqa: E402


LEGACY_DIRS = ("checkpoints", "handoffs", "ledgers", "layers", "reports")
TEXT_SUFFIXES = {".md", ".json", ".jsonl", ".txt"}


def is_project_scoped(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return len(relative.parts) >= 2 and relative.parts[0] == "projects"


def safe_file_record(path: Path, root: Path) -> dict[str, object]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        raw = ""
    findings = public_findings(raw) if raw else []
    try:
        relative = str(path.relative_to(root))
    except ValueError:
        relative = str(path)
    legacy_kind = legacy_kind_for(relative)
    return {
        "path": relative,
        "bytes": path.stat().st_size,
        "hash": content_hash(raw) if raw else "",
        "red_findings": findings,
        "legacy_kind": legacy_kind,
        "recall_default": False,
        "migration_status": migration_status_for(legacy_kind),
    }


def legacy_kind_for(relative: str) -> str:
    if relative.startswith("ledgers/claude-import/"):
        return "claude_import_legacy"
    return "legacy_runtime"


def migration_status_for(legacy_kind: str) -> str:
    if legacy_kind == "claude_import_legacy":
        return "legacy_migrable_project_assignment_required"
    return "manual_review"


def audit(root: Path) -> dict[str, object]:
    candidates: list[dict[str, object]] = []
    for dirname in LEGACY_DIRS:
        base = root / dirname
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
                continue
            if is_project_scoped(path, root):
                continue
            candidates.append(safe_file_record(path, root))
    red_count = sum(1 for item in candidates if item["red_findings"])
    return {
        "mode": "report-only",
        "ralph_home": str(root),
        "legacy_candidate_count": len(candidates),
        "red_candidate_count": red_count,
        "apply_supported": False,
        "candidates": candidates,
    }


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# Ralph Legacy Runtime Audit",
        "",
        f"Mode: {report['mode']}",
        f"Ralph home: `{report['ralph_home']}`",
        f"Legacy candidates: {report['legacy_candidate_count']}",
        f"RED candidates: {report['red_candidate_count']}",
        "",
        "Legacy runtime files are not migrated automatically. Files without project metadata require manual review.",
        "",
    ]
    candidates = report["candidates"]
    if not candidates:
        lines.append("No legacy candidates found.")
        return "\n".join(lines) + "\n"
    lines.extend(["| Path | Bytes | Hash | Kind | Recall default | Status |", "|---|---:|---|---|---|---|"])
    for item in candidates:
        recall_default = "yes" if item["recall_default"] else "no"
        lines.append(
            f"| {item['path']} | {item['bytes']} | {str(item['hash'])[:12]} | {item['legacy_kind']} | {recall_default} | {item['migration_status']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Report legacy Ralph runtime files that are not project-scoped.")
    parser.add_argument("--ralph-home", default=str(ralph_home()))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--suggest-migration", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Reserved; currently refused.")
    args = parser.parse_args()

    if args.apply:
        print("LEGACY_AUDIT_APPLY_REFUSED report-only migration requires explicit future approval", file=sys.stderr)
        return 2
    report = audit(Path(args.ralph_home).expanduser())
    if args.suggest_migration:
        report["suggestion"] = "Use path/cwd/git metadata to assign each candidate manually; skip RED and ambiguous files."
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_markdown(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
