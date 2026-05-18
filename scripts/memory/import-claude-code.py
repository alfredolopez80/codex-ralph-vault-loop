#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CLAUDE_ROOT = Path("~/.claude/projects").expanduser()
DEFAULT_RALPH_HOME = Path("~/.ralph-codex").expanduser()
DEFAULT_PROJECT = "codex-ralph-vault-loop"
DEFAULT_MAX_SESSION_CHARS = 12_000
HOOKS_DIR = REPO_ROOT / ".codex" / "hooks"
SKIP_PATH_PARTS = (
    ".env",
    "id_rsa",
    "id_ed25519",
    "secret",
    "secrets",
    "token",
    "credential",
    "wallet",
    "keystore",
    "private",
)
IMPORTER_NAME = "import-claude-code.py"


@dataclass(frozen=True)
class ImportCandidate:
    source: str
    origin_path: Path
    content: str


@dataclass(frozen=True)
class PreparedImport:
    source: str
    origin_path: str
    classification: str
    digest: str
    filename: str
    bytes: int
    duplicate: bool
    project_id: str = ""
    workspace_root: str = ""


@dataclass
class Summary:
    scanned_memory_md: int = 0
    scanned_jsonl: int = 0
    prepared: int = 0
    written: int = 0
    skipped_red: int = 0
    skipped_duplicate: int = 0
    skipped_sensitive_path: int = 0
    skipped_since: int = 0
    read_errors: int = 0
    parse_errors: int = 0


def load_sensitive_classifier():
    security_dir = REPO_ROOT / "scripts" / "security"
    if str(security_dir) not in sys.path:
        sys.path.insert(0, str(security_dir))
    try:
        from sensitive_content import classify_text  # type: ignore
    except Exception:
        return None
    return classify_text


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def yaml_scalar(value: object) -> str:
    return json.dumps("" if value is None else str(value), ensure_ascii=True)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-._")
    return slug or "claude-import"


def safe_project_id(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise ValueError("--project-id may contain only letters, numbers, dot, underscore, and dash")
    return value


def derive_context(workspace_root: str) -> object | None:
    if not workspace_root:
        return None
    if str(HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(HOOKS_DIR))
    try:
        from shared.active_context import active_context_from_payload  # type: ignore
    except Exception:
        return None
    return active_context_from_payload({"cwd": workspace_root, "session_id": os.environ.get("CODEX_SESSION_ID", "claude-import")})


def runtime_root(args: argparse.Namespace) -> Path:
    base = Path(args.ralph_home).expanduser()
    if args.project_id:
        return base / "projects" / args.project_id
    return base


def import_dir(args: argparse.Namespace) -> Path:
    return runtime_root(args) / "ledgers" / "claude-import"


def report_dir(args: argparse.Namespace) -> Path:
    return runtime_root(args) / "reports"


def ensure_project_metadata(args: argparse.Namespace) -> None:
    if not args.project_id:
        return
    root = runtime_root(args)
    root.mkdir(parents=True, exist_ok=True)
    metadata = {
        "project_id": args.project_id,
        "project_slug": args.project,
        "workspace_root": args.workspace_root,
        "source": IMPORTER_NAME,
        "updated_at": now_iso(),
    }
    (root / "project.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def path_is_sensitive(path: Path) -> bool:
    lowered_parts = [part.lower() for part in path.parts]
    for part in lowered_parts:
        if part == "private":
            continue
        if any(marker in part for marker in SKIP_PATH_PARTS):
            return True
    return False


def within_since(path: Path, since_days: int | None) -> bool:
    if since_days is None:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return modified >= cutoff


def iter_source_files(root: Path, since_days: int | None, limit: int | None, summary: Summary) -> Iterable[Path]:
    if not root.exists():
        return
    yielded = 0
    candidates = sorted(root.glob("**/memory/*.md")) + sorted(root.glob("**/*.jsonl"))
    for path in candidates:
        if limit is not None and yielded >= limit:
            break
        if path_is_sensitive(path):
            summary.skipped_sensitive_path += 1
            continue
        if not path.is_file():
            continue
        try:
            if not within_since(path, since_days):
                summary.skipped_since += 1
                continue
        except OSError:
            summary.read_errors += 1
            continue
        yielded += 1
        yield path


def text_from_content(content: object, include_tool_results: bool) -> list[str]:
    if content is None:
        return []
    if isinstance(content, str):
        text = content.strip()
        return [text] if text else []
    if isinstance(content, dict):
        block_type = str(content.get("type") or "")
        if "tool_result" in block_type:
            if not include_tool_results:
                return []
            if "content" in content:
                return text_from_content(content.get("content"), include_tool_results)
            tool_id = content.get("tool_use_id") or content.get("id") or "unknown"
            return [f"[tool_result metadata id={tool_id}]"]
        if "tool" in block_type and "text" not in content:
            name = content.get("name") or content.get("tool_name") or block_type or "tool"
            tool_id = content.get("id") or content.get("tool_use_id") or "unknown"
            return [f"[tool metadata name={name} id={tool_id}]"]
        if "text" in content:
            return text_from_content(content.get("text"), include_tool_results)
        if include_tool_results and "content" in content:
            return text_from_content(content.get("content"), include_tool_results)
        return []
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            parts.extend(text_from_content(item, include_tool_results))
        return parts
    return []


def extract_jsonl_entry(obj: object, include_tool_results: bool) -> list[str]:
    if not isinstance(obj, dict):
        return []
    message = obj.get("message") if isinstance(obj.get("message"), dict) else obj
    if not isinstance(message, dict):
        return []

    role = str(message.get("role") or obj.get("role") or obj.get("type") or "entry")
    entry_type = str(obj.get("type") or message.get("type") or "")
    if "tool_result" in entry_type and not include_tool_results:
        return []

    content = message.get("content")
    if content is None:
        content = obj.get("content")
    if content is None:
        content = obj.get("text")

    parts = text_from_content(content, include_tool_results)
    if not parts and "text" in message:
        parts = text_from_content(message.get("text"), include_tool_results)
    if not parts:
        return []

    lines = []
    for part in parts:
        clean = re.sub(r"\s+", " ", part).strip()
        if clean:
            lines.append(f"{role}: {clean}")
    return lines


def read_memory_markdown(path: Path, summary: Summary) -> ImportCandidate | None:
    summary.scanned_memory_md += 1
    try:
        content = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        summary.read_errors += 1
        return None
    if not content:
        return None
    return ImportCandidate(source="claude_memory_md", origin_path=path, content=content)


def read_jsonl_session(path: Path, include_tool_results: bool, max_chars: int, summary: Summary) -> ImportCandidate | None:
    summary.scanned_jsonl += 1
    lines: list[str] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    obj = json.loads(raw_line)
                except json.JSONDecodeError:
                    summary.parse_errors += 1
                    continue
                lines.extend(extract_jsonl_entry(obj, include_tool_results))
                if sum(len(line) + 1 for line in lines) >= max_chars:
                    break
    except OSError:
        summary.read_errors += 1
        return None

    content = "\n".join(lines).strip()
    if not content:
        return None
    return ImportCandidate(source="claude_jsonl_session", origin_path=path, content=content)


def safe_report(candidate: ImportCandidate, classifier, max_chars: int, summary: Summary) -> tuple[str, str] | None:
    requested = "YELLOW"
    if classifier is None:
        safe_text = candidate.content
        classification = requested
    else:
        report = classifier(candidate.content, requested)
        classification = getattr(report, "classification", requested)
        if classification == "RED":
            summary.skipped_red += 1
            return None
        safe_text = getattr(report, "redacted_text", candidate.content)

    if candidate.source == "claude_jsonl_session" and len(safe_text) > max_chars:
        safe_text = safe_text[:max_chars].rstrip() + "\n...[truncated]\n"
    return classification, safe_text


def render_import_note(
    *,
    candidate: ImportCandidate,
    classification: str,
    safe_text: str,
    project: str,
    project_id: str,
    workspace_root: str,
    digest: str,
) -> str:
    metadata = {
        "created_at": now_iso(),
        "classification": classification,
        "source": candidate.source,
        "origin_path": str(candidate.origin_path),
        "project": project,
        "source_project_id": project_id,
        "source_project_slug": project,
        "source_workspace_root": workspace_root,
        "hash": digest,
        "imported_by": IMPORTER_NAME,
    }
    lines = ["---"]
    lines.extend(f"{key}: {yaml_scalar(value)}" for key, value in metadata.items())
    lines.extend(["---", "", safe_text.strip(), ""])
    return "\n".join(lines)


def existing_hashes(index_path: Path) -> set[str]:
    hashes: set[str] = set()
    if not index_path.exists():
        return hashes
    try:
        with index_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                digest = item.get("hash")
                if isinstance(digest, str):
                    hashes.add(digest)
    except OSError:
        return hashes
    return hashes


def prepare_imports(args: argparse.Namespace, summary: Summary) -> list[tuple[PreparedImport, str]]:
    classifier = load_sensitive_classifier()
    root = Path(args.claude_root).expanduser()
    target_import_dir = import_dir(args)
    index_path = target_import_dir / "index.jsonl"
    seen_hashes = existing_hashes(index_path)
    prepared: list[tuple[PreparedImport, str]] = []
    in_run_hashes: set[str] = set()

    for path in iter_source_files(root, args.since_days, args.limit, summary):
        candidate = (
            read_memory_markdown(path, summary)
            if path.suffix == ".md"
            else read_jsonl_session(path, args.include_tool_results, args.max_session_chars, summary)
        )
        if candidate is None:
            continue
        safe = safe_report(candidate, classifier, args.max_session_chars, summary)
        if safe is None:
            continue
        classification, safe_text = safe
        digest = content_hash(safe_text)
        duplicate = digest in seen_hashes or digest in in_run_hashes
        if duplicate:
            summary.skipped_duplicate += 1
        in_run_hashes.add(digest)

        stem = slugify(candidate.origin_path.stem)
        filename = f"{stem}-{digest[:12]}.md"
        rendered = render_import_note(
            candidate=candidate,
            classification=classification,
            safe_text=safe_text,
            project=args.project,
            project_id=args.project_id,
            workspace_root=args.workspace_root,
            digest=digest,
        )
        item = PreparedImport(
            source=candidate.source,
            origin_path=str(candidate.origin_path),
            classification=classification,
            digest=digest,
            filename=filename,
            bytes=len(rendered.encode("utf-8")),
            duplicate=duplicate,
            project_id=args.project_id,
            workspace_root=args.workspace_root,
        )
        summary.prepared += 1
        prepared.append((item, rendered))
    return prepared


def apply_imports(args: argparse.Namespace, prepared: list[tuple[PreparedImport, str]], summary: Summary) -> None:
    target_import_dir = import_dir(args)
    target_report_dir = report_dir(args)
    ensure_project_metadata(args)
    target_import_dir.mkdir(parents=True, exist_ok=True)
    target_report_dir.mkdir(parents=True, exist_ok=True)
    index_path = target_import_dir / "index.jsonl"

    with index_path.open("a", encoding="utf-8") as index:
        for item, rendered in prepared:
            if item.duplicate:
                continue
            output_path = target_import_dir / item.filename
            if output_path.exists():
                summary.skipped_duplicate += 1
                continue
            output_path.write_text(rendered, encoding="utf-8")
            index.write(json.dumps(asdict(item), sort_keys=True) + "\n")
            summary.written += 1

    report_path = target_report_dir / "claude-import-latest.json"
    report_path.write_text(json.dumps(asdict(summary), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_markdown(args: argparse.Namespace, summary: Summary, prepared: list[tuple[PreparedImport, str]]) -> str:
    mode = "apply" if args.apply else "dry-run"
    lines = [
        "# Claude Code Import",
        "",
        f"- mode: `{mode}`",
        f"- project: `{args.project}`",
        f"- project_id: `{args.project_id or 'legacy'}`",
        f"- runtime_root: `{runtime_root(args)}`",
        f"- scanned_memory_md: `{summary.scanned_memory_md}`",
        f"- scanned_jsonl: `{summary.scanned_jsonl}`",
        f"- prepared: `{summary.prepared}`",
        f"- written: `{summary.written}`",
        f"- skipped_red: `{summary.skipped_red}`",
        f"- skipped_duplicate: `{summary.skipped_duplicate}`",
        f"- skipped_sensitive_path: `{summary.skipped_sensitive_path}`",
        f"- skipped_since: `{summary.skipped_since}`",
        f"- read_errors: `{summary.read_errors}`",
        f"- parse_errors: `{summary.parse_errors}`",
        "",
        "## Prepared Files",
        "",
    ]
    if not prepared:
        lines.append("No safe imports prepared.")
    else:
        for item, _rendered in prepared[:20]:
            suffix = " duplicate" if item.duplicate else ""
            lines.append(f"- `{item.filename}` source=`{item.source}` classification=`{item.classification}`{suffix}")
    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely import Claude Code local memory into Ralph/Codex ledgers.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview imports without writing. This is the default.")
    mode.add_argument("--apply", action="store_true", help="Write sanitized imports under ~/.ralph-codex.")
    parser.add_argument("--claude-root", default=str(DEFAULT_CLAUDE_ROOT))
    parser.add_argument("--ralph-home", default=os.environ.get("RALPH_HOME", str(DEFAULT_RALPH_HOME)))
    parser.add_argument("--project", default="")
    parser.add_argument("--project-id", default=os.environ.get("RALPH_PROJECT_ID", ""))
    parser.add_argument("--workspace-root", default=os.environ.get("RALPH_WORKSPACE_ROOT", ""))
    parser.add_argument("--since-days", type=int)
    parser.add_argument("--max-session-chars", type=int, default=DEFAULT_MAX_SESSION_CHARS)
    parser.add_argument("--include-tool-results", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.since_days is not None and args.since_days < 0:
        parser.error("--since-days must be >= 0")
    if args.max_session_chars < 1:
        parser.error("--max-session-chars must be >= 1")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be >= 1")
    args.workspace_root = str(Path(args.workspace_root).expanduser().resolve()) if args.workspace_root else ""
    context = derive_context(args.workspace_root)
    if context is not None:
        if not args.project:
            args.project = getattr(context, "project_slug", "") or ""
        if not args.project_id:
            args.project_id = getattr(context, "project_id", "") or ""
    if not args.project:
        args.project = DEFAULT_PROJECT
    args.project = slugify(args.project)
    try:
        args.project_id = safe_project_id(args.project_id)
    except ValueError as exc:
        parser.error(str(exc))
    args.claude_root = str(Path(args.claude_root).expanduser())
    args.ralph_home = str(Path(args.ralph_home).expanduser())
    return args


def main() -> int:
    args = parse_args()
    summary = Summary()
    prepared = prepare_imports(args, summary)
    if args.apply:
        apply_imports(args, prepared, summary)

    payload = {
        "mode": "apply" if args.apply else "dry-run",
        "project": args.project,
        "project_id": args.project_id,
        "runtime_root": str(runtime_root(args)),
        "summary": asdict(summary),
        "prepared": [asdict(item) for item, _rendered in prepared],
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_markdown(args, summary, prepared), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
