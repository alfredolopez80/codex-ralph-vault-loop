from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from implementation_notes_lib import ImplementationNotesError, ensure_not_red, now_local, resolve_for_write, run_git


INDEX_JSON_NAME = "implementation-index.json"
INDEX_MD_NAME = "implementation-index.md"
INDEX_VERSION = 1


def _rel(path: Path, root: Path) -> str:
    resolved = path.resolve(strict=False)
    try:
        return resolved.relative_to(root.resolve(strict=False)).as_posix()
    except ValueError:
        return str(resolved)


def index_json_path(primary_root: Path) -> Path:
    return resolve_for_write(primary_root / ".ralph" / "plans" / INDEX_JSON_NAME, primary_root)


def index_md_path(primary_root: Path) -> Path:
    return resolve_for_write(primary_root / ".ralph" / "plans" / INDEX_MD_NAME, primary_root)


def current_git_metadata(root: Path) -> dict[str, str]:
    return {
        "branch": run_git(root, "branch", "--show-current") or run_git(root, "rev-parse", "--abbrev-ref", "HEAD"),
        "commit": run_git(root, "rev-parse", "HEAD"),
    }


def empty_index(primary_root: Path) -> dict[str, Any]:
    return {
        "version": INDEX_VERSION,
        "canonical_repo_root": str(primary_root.resolve()),
        "updated_at": now_local(),
        "plans": [],
        "loose_commits": [],
    }


def load_index(primary_root: Path) -> dict[str, Any]:
    path = index_json_path(primary_root)
    if not path.exists():
        return empty_index(primary_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ImplementationNotesError(f"implementation index is not valid JSON: {path}") from exc
    if not isinstance(data, dict):
        raise ImplementationNotesError(f"implementation index must be a JSON object: {path}")
    data.setdefault("version", INDEX_VERSION)
    data["canonical_repo_root"] = str(primary_root.resolve())
    data.setdefault("plans", [])
    data.setdefault("loose_commits", [])
    if not isinstance(data["plans"], list) or not isinstance(data["loose_commits"], list):
        raise ImplementationNotesError("implementation index plans and loose_commits must be lists")
    return data


def _add_unique(values: list[str], value: str) -> list[str]:
    if value and value not in values:
        values.append(value)
    return values


def _md_cell(value: object) -> str:
    return str(value or "").replace("\n", " ").replace("|", "\\|")


def upsert_plan_entry(
    *,
    primary_root: Path,
    plan_path: Path,
    notes_path: Path,
    status: str,
    active_root: Path,
    commit: str = "",
    branch: str = "",
    pr: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    data = load_index(primary_root)
    timestamp = now_local()
    plan_rel = _rel(plan_path, primary_root)
    notes_rel = _rel(notes_path, primary_root)
    git_meta = current_git_metadata(active_root)
    branch = branch or git_meta["branch"]
    commit = commit or ""

    entry = next((item for item in data["plans"] if isinstance(item, dict) and item.get("plan") == plan_rel), None)
    if entry is None:
        entry = {
            "type": "plan",
            "plan": plan_rel,
            "notes": notes_rel,
            "status": status,
            "branch": branch,
            "commits": [],
            "pr": pr,
            "session_id": session_id,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        data["plans"].append(entry)
    else:
        entry["notes"] = notes_rel
        entry["status"] = status or entry.get("status", "")
        entry["branch"] = branch or entry.get("branch", "")
        entry["pr"] = pr or entry.get("pr", "")
        entry["session_id"] = session_id or entry.get("session_id", "")
        entry["updated_at"] = timestamp
        entry.setdefault("commits", [])

    if commit:
        entry["commits"] = _add_unique([str(value) for value in entry.get("commits", [])], commit)
    latest = git_meta["commit"]
    if latest:
        entry["latest_git_sha"] = latest
    write_index(primary_root, data)
    return entry


def record_loose_commit(
    *,
    primary_root: Path,
    commit: str,
    active_root: Path,
    reason: str,
    branch: str = "",
    notes: str = "",
) -> dict[str, Any]:
    if not commit.strip():
        raise ImplementationNotesError("loose commit is required")
    ensure_not_red("loose commit index entry", "\n".join([commit, reason, branch, notes]))
    data = load_index(primary_root)
    timestamp = now_local()
    git_meta = current_git_metadata(active_root)
    branch = branch or git_meta["branch"]
    entry = next((item for item in data["loose_commits"] if isinstance(item, dict) and item.get("commit") == commit), None)
    if entry is None:
        entry = {
            "type": "loose_commit",
            "commit": commit,
            "branch": branch,
            "reason": reason,
            "notes": notes,
            "linked_plan": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        data["loose_commits"].append(entry)
    else:
        entry["branch"] = branch or entry.get("branch", "")
        entry["reason"] = reason or entry.get("reason", "")
        entry["notes"] = notes or entry.get("notes", "")
        entry["updated_at"] = timestamp
    write_index(primary_root, data)
    return entry


def write_index(primary_root: Path, data: dict[str, Any]) -> None:
    data["version"] = INDEX_VERSION
    data["canonical_repo_root"] = str(primary_root.resolve())
    data["updated_at"] = now_local()
    rendered_json = json.dumps(data, indent=2, sort_keys=True) + "\n"
    rendered_md = render_markdown(data)
    ensure_not_red("implementation index JSON", rendered_json)
    ensure_not_red("implementation index Markdown", rendered_md)
    json_path = index_json_path(primary_root)
    md_path = index_md_path(primary_root)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(rendered_json, encoding="utf-8")
    md_path.write_text(rendered_md, encoding="utf-8")


def render_markdown(data: dict[str, Any]) -> str:
    lines = [
        "# Implementation Index",
        "",
        f"Canonical repo root: `{data.get('canonical_repo_root', '')}`",
        f"Updated at: `{data.get('updated_at', '')}`",
        "",
        "## Plans",
        "",
        "| Status | Plan | Notes | Branch | Commits | PR | Updated |",
        "|---|---|---|---|---|---|---|",
    ]
    plans = [item for item in data.get("plans", []) if isinstance(item, dict)]
    if plans:
        for item in plans:
            commits = ", ".join(f"`{value}`" for value in item.get("commits", []) if value) or "n/a"
            pr = item.get("pr") or "n/a"
            lines.append(
                "| {status} | [{plan}]({plan}) | [{notes}]({notes}) | `{branch}` | {commits} | {pr} | `{updated}` |".format(
                    status=item.get("status", ""),
                    plan=_md_cell(item.get("plan", "")),
                    notes=_md_cell(item.get("notes", "")),
                    branch=_md_cell(item.get("branch", "")),
                    commits=commits,
                    pr=_md_cell(pr),
                    updated=item.get("updated_at", ""),
                )
            )
    else:
        lines.append("| n/a | n/a | n/a | n/a | n/a | n/a | n/a |")

    lines.extend(
        [
            "",
            "## Loose Commits",
            "",
            "| Commit | Branch | Reason | Notes | Updated |",
            "|---|---|---|---|---|",
        ]
    )
    loose = [item for item in data.get("loose_commits", []) if isinstance(item, dict)]
    if loose:
        for item in loose:
            lines.append(
                "| `{commit}` | `{branch}` | {reason} | {notes} | `{updated}` |".format(
                    commit=_md_cell(item.get("commit", "")),
                    branch=_md_cell(item.get("branch", "")),
                    reason=_md_cell(item.get("reason", "")),
                    notes=_md_cell(item.get("notes", "")),
                    updated=item.get("updated_at", ""),
                )
            )
    else:
        lines.append("| n/a | n/a | n/a | n/a | n/a |")
    return "\n".join(lines) + "\n"
