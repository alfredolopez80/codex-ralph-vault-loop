from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
SECURITY_ROOT = ROOT / "scripts" / "security"
if str(SECURITY_ROOT) not in sys.path:
    sys.path.insert(0, str(SECURITY_ROOT))

from sensitive_content import classify_text  # noqa: E402


CODEX_WORKTREE_ROOT = Path.home() / ".codex" / "worktrees"
IMPLEMENTATION_NOTES_SUFFIX = "-implementation-notes.html"
GLOBAL_APPEND_ANCHOR = "    <!-- IMPLEMENTATION_NOTES_APPEND_ANCHOR -->"
ALLOWED_CATEGORIES = {"decision", "deviation", "tradeoff", "open-question", "validation", "summary"}
CATEGORY_LABELS = {
    "decision": "Design Decisions",
    "deviation": "Deviations From Spec",
    "tradeoff": "Tradeoffs Considered",
    "open-question": "Open Questions",
    "validation": "Validation Notes",
    "summary": "Final Implementation Summary",
}
CATEGORY_HEADING_IDS = {
    "decision": "decisions-heading",
    "deviation": "deviations-heading",
    "tradeoff": "tradeoffs-heading",
    "open-question": "questions-heading",
    "validation": "validation-heading",
    "summary": "final-heading",
}
CATEGORY_ORDER = ("decision", "deviation", "tradeoff", "open-question", "validation", "summary")
SENSITIVE_NAME_RE = re.compile(r"(?i)(^\.env(?:\.|$)|secret|token|credential|wallet|keystore|cookies?|id_rsa|id_ed25519|\.pem$|\.key$)")


class ImplementationNotesError(RuntimeError):
    pass


@dataclass(frozen=True)
class Roots:
    active_worktree_root: Path
    primary_repo_root: Path


@dataclass(frozen=True)
class PlanMetadata:
    implementation_notes: str
    implementation_notes_required: bool
    implementation_notes_status: str
    plan_approval_status: str


@dataclass
class ParsedEntry:
    category: str
    section: str
    fields: dict[str, str]


class NotesHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.has_main = False
        self.has_csp = False
        self.section_stack: list[str] = []
        self.section_counts: dict[str, int] = {}
        self.anchor_sections: dict[str, str] = {}
        self.entries: list[ParsedEntry] = []
        self.current_entry: ParsedEntry | None = None
        self.current_field_tag = ""
        self.current_field_text: list[str] = []
        self.pending_dt = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "meta" and values.get("http-equiv", "").lower() == "content-security-policy":
            content = values.get("content", "")
            self.has_csp = "default-src 'none'" in content and "style-src 'unsafe-inline'" in content
        if tag == "main" and values.get("data-implementation-notes") == "true":
            self.has_main = True
        if tag == "section":
            category = values.get("data-entry-section", "")
            self.section_stack.append(category)
            if category:
                self.section_counts[category] = self.section_counts.get(category, 0) + 1
        if tag == "article":
            classes = set(values.get("class", "").split())
            if "entry" in classes:
                self.current_entry = ParsedEntry(
                    category=values.get("data-entry-kind", ""),
                    section=self.current_section(),
                    fields={},
                )
                self.pending_dt = ""
        if self.current_entry is not None and tag in {"dt", "dd"}:
            self.current_field_tag = tag
            self.current_field_text = []

    def handle_endtag(self, tag: str) -> None:
        if self.current_entry is not None and tag == self.current_field_tag:
            text = " ".join("".join(self.current_field_text).split())
            if tag == "dt":
                self.pending_dt = text
            elif tag == "dd" and self.pending_dt:
                self.current_entry.fields[self.pending_dt] = text
                self.pending_dt = ""
            self.current_field_tag = ""
            self.current_field_text = []
        if tag == "article" and self.current_entry is not None:
            self.entries.append(self.current_entry)
            self.current_entry = None
            self.pending_dt = ""
        if tag == "section" and self.section_stack:
            self.section_stack.pop()

    def handle_data(self, data: str) -> None:
        if self.current_entry is not None and self.current_field_tag:
            self.current_field_text.append(data)

    def handle_comment(self, data: str) -> None:
        stripped = data.strip()
        match = re.fullmatch(r"IMPLEMENTATION_NOTES_([A-Z_]+)_ANCHOR", stripped)
        if not match:
            return
        normalized = match.group(1).lower().replace("_", "-")
        self.anchor_sections[normalized] = self.current_section()

    def current_section(self) -> str:
        for category in reversed(self.section_stack):
            if category:
                return category
        return ""


def now_local() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def safe_session_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())[:80].strip("._-")
    return safe or "unknown"


def hook_state_root(active_root: Path) -> Path:
    override = os.environ.get("CODEX_HOOK_STATE_ROOT")
    if override and Path(override).is_absolute():
        return Path(override).expanduser()
    return active_root / ".codex" / "state"


def implementation_plan_state_path(active_root: Path, session_id: str) -> Path:
    return hook_state_root(active_root) / safe_session_id(session_id) / "implementation-notes-plan.json"


def write_implementation_plan_state(roots: Roots, session_id: str, plan_path: Path, notes_path: Path) -> None:
    if safe_session_id(session_id) == "unknown":
        return
    path = implementation_plan_state_path(roots.active_worktree_root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "session_id": safe_session_id(session_id),
        "plan_path": str(plan_path),
        "implementation_notes_path": str(notes_path),
        "primary_repo_root": str(roots.primary_repo_root),
        "active_worktree_root": str(roots.active_worktree_root),
        "updated_at": now_local(),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_implementation_plan_state(active_root: Path, session_id: str) -> dict[str, str]:
    path = implementation_plan_state_path(active_root, session_id)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    if safe_session_id(str(data.get("session_id") or "")) != safe_session_id(session_id):
        return {}
    return {str(key): str(value) for key, value in data.items() if isinstance(value, str)}


def run_git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=3,
        )
    except Exception:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def git_root_for(path: Path) -> Path:
    root = run_git(path, "rev-parse", "--show-toplevel")
    if not root:
        raise ImplementationNotesError(f"not inside a git repository: {path}")
    return Path(root).resolve()


def is_codex_worktree(path: Path) -> bool:
    try:
        path.resolve().relative_to(CODEX_WORKTREE_ROOT.resolve())
        return True
    except ValueError:
        return False


def _worktree_paths(root: Path) -> list[Path]:
    raw = run_git(root, "worktree", "list", "--porcelain")
    paths: list[Path] = []
    for line in raw.splitlines():
        if line.startswith("worktree "):
            candidate = Path(line.removeprefix("worktree ")).expanduser()
            if candidate.exists():
                paths.append(candidate.resolve())
    return paths


def resolve_roots(active_root: str | Path | None = None, primary_root: str | Path | None = None) -> Roots:
    active = Path(active_root or os.environ.get("RALPH_ACTIVE_WORKTREE_ROOT") or Path.cwd()).expanduser().resolve()
    active_git = git_root_for(active)
    explicit_primary = primary_root or os.environ.get("RALPH_PRIMARY_REPO_ROOT")
    if explicit_primary:
        primary = git_root_for(Path(explicit_primary).expanduser().resolve())
        if is_codex_worktree(primary):
            raise ImplementationNotesError("primary repo root cannot be under ~/.codex/worktrees")
        return Roots(active_worktree_root=active_git, primary_repo_root=primary)

    if not is_codex_worktree(active_git):
        return Roots(active_worktree_root=active_git, primary_repo_root=active_git)

    for candidate in _worktree_paths(active_git):
        if candidate.name == active_git.name and not is_codex_worktree(candidate):
            return Roots(active_worktree_root=active_git, primary_repo_root=candidate)

    raise ImplementationNotesError(
        "could not resolve a canonical local repo root outside ~/.codex/worktrees; set RALPH_PRIMARY_REPO_ROOT"
    )


def ensure_not_red(label: str, value: object) -> None:
    report = classify_text("" if value is None else str(value))
    if report.classification == "RED":
        findings = ",".join(finding.label for finding in report.findings) or "classified_red"
        raise ImplementationNotesError(f"{label} contains RED-sensitive material; refusing to persist it ({findings})")


def _has_sensitive_name(path: Path) -> bool:
    return any(SENSITIVE_NAME_RE.search(part) for part in path.parts)


def _has_parent_traversal(path: Path) -> bool:
    return any(part == ".." for part in path.expanduser().parts)


def _allowed_roots(primary_root: Path, allow_docs: bool) -> list[Path]:
    roots = [(primary_root / ".ralph" / "plans").resolve()]
    if allow_docs:
        roots.append((primary_root / "docs").resolve())
    return roots


def resolve_for_read(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if _has_parent_traversal(candidate):
        raise ImplementationNotesError(f"path traversal is not allowed: {path}")
    resolved = candidate.resolve()
    if _has_sensitive_name(resolved):
        raise ImplementationNotesError(f"sensitive filename is not allowed: {path}")
    if not resolved.exists():
        raise ImplementationNotesError(f"path does not exist: {path}")
    return resolved


def resolve_for_write(path: str | Path, primary_root: Path, allow_docs: bool = False) -> Path:
    candidate = Path(path).expanduser()
    if _has_parent_traversal(candidate):
        raise ImplementationNotesError(f"path traversal is not allowed: {path}")
    if _has_sensitive_name(candidate):
        raise ImplementationNotesError(f"sensitive filename is not allowed: {path}")
    resolved = candidate.resolve(strict=False)
    if _has_sensitive_name(resolved):
        raise ImplementationNotesError(f"sensitive filename is not allowed: {path}")
    allowed = _allowed_roots(primary_root, allow_docs)
    if not any(_is_relative_to(resolved, root) for root in allowed):
        raise ImplementationNotesError(f"write path escapes allowed repo-local roots: {path}")
    if resolved.exists() and resolved.is_symlink():
        target = resolved.resolve()
        if not any(_is_relative_to(target, root) for root in allowed):
            raise ImplementationNotesError(f"symlink target escapes allowed roots: {path}")
    if not any(_is_relative_to(resolved.parent.resolve(strict=False), root) for root in allowed):
        raise ImplementationNotesError(f"write parent escapes allowed repo-local roots: {path}")
    return resolved


def ensure_plan_path_allowed(plan_path: Path, roots: Roots) -> None:
    allowed = [
        (roots.active_worktree_root / ".ralph" / "plans").resolve(),
        (roots.primary_repo_root / ".ralph" / "plans").resolve(),
    ]
    if any(_is_relative_to(plan_path, root) for root in allowed):
        return
    raise ImplementationNotesError(f"plan path escapes active/canonical .ralph/plans roots: {plan_path}")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def parse_plan_metadata(plan_path: Path) -> PlanMetadata:
    values: dict[str, str] = {}
    in_fence = False
    for line in plan_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
        if normalized in {
            "implementation_notes",
            "implementation_notes_required",
            "implementation_notes_status",
            "plan_approval_status",
        } and normalized not in values:
            values[normalized] = value.strip()
    return PlanMetadata(
        implementation_notes=values.get("implementation_notes", ""),
        implementation_notes_required=values.get("implementation_notes_required", "").lower() in {"yes", "true", "required"},
        implementation_notes_status=values.get("implementation_notes_status", ""),
        plan_approval_status=values.get("plan_approval_status", ""),
    )


def is_plan_approved(metadata: PlanMetadata, explicit_approved: bool = False) -> bool:
    return explicit_approved or metadata.plan_approval_status.strip().lower() == "approved"


def infer_notes_path(plan_path: Path, primary_root: Path) -> Path:
    stem = plan_path.name[:-3] if plan_path.name.endswith(".md") else plan_path.stem
    return primary_root / ".ralph" / "plans" / f"{stem}{IMPLEMENTATION_NOTES_SUFFIX}"


def canonical_plan_path(plan_path: Path, primary_root: Path) -> Path:
    return primary_root / ".ralph" / "plans" / plan_path.name


def resolve_notes_path_for_plan(
    metadata: PlanMetadata,
    plan_path: Path,
    primary_root: Path,
    *,
    explicit_notes: str | Path | None = None,
    allow_docs: bool = False,
) -> Path:
    canonical_plan = canonical_plan_path(plan_path, primary_root)
    if explicit_notes:
        raw_notes = Path(explicit_notes).expanduser()
    elif metadata.implementation_notes:
        raw_notes = Path(metadata.implementation_notes.replace("<primary-repo-root>", str(primary_root))).expanduser()
        if is_codex_worktree(raw_notes.resolve(strict=False)):
            raw_notes = infer_notes_path(canonical_plan, primary_root)
    else:
        raw_notes = infer_notes_path(canonical_plan, primary_root)
    return resolve_for_write(raw_notes, primary_root, allow_docs=allow_docs)


def canonicalize_plan_metadata_text(text: str, notes_path: Path) -> str:
    lines = text.splitlines()
    rendered: list[str] = []
    replaced = False
    in_fence = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            rendered.append(line)
            continue
        normalized = ""
        if not in_fence and ":" in line:
            key, _value = line.split(":", 1)
            normalized = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
        if normalized == "implementation_notes" and not replaced:
            rendered.append(f"Implementation notes: {notes_path}")
            replaced = True
        else:
            rendered.append(line)
    if not replaced:
        insert_at = 0
        for index, line in enumerate(rendered):
            if line.startswith("# "):
                insert_at = index + 1
                break
        rendered.insert(insert_at, f"Implementation notes: {notes_path}")
    return "\n".join(rendered) + ("\n" if text.endswith("\n") else "")


def sync_plan_to_primary(plan_path: Path, primary_root: Path, notes_path: Path, force: bool = False) -> Path:
    target = resolve_for_write(canonical_plan_path(plan_path, primary_root), primary_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = canonicalize_plan_metadata_text(plan_path.read_text(encoding="utf-8"), notes_path)
    if target.exists() and target.read_text(encoding="utf-8") != rendered and not force:
        raise ImplementationNotesError(f"canonical plan differs; use --force to replace: {target}")
    if not target.exists() or force:
        target.write_text(rendered, encoding="utf-8")
    return target


def html_escape(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def category_anchor(category: str) -> str:
    normalized = category.replace("-", "_").upper()
    return f"      <!-- IMPLEMENTATION_NOTES_{normalized}_ANCHOR -->"


def category_section(category: str) -> str:
    return (
        f'    <section class="entry-section" data-entry-section="{html_escape(category)}" '
        f'aria-labelledby="{html_escape(CATEGORY_HEADING_IDS[category])}">\n'
        f'      <h2 id="{html_escape(CATEGORY_HEADING_IDS[category])}">{html_escape(section_for_category(category))}</h2>\n'
        f"{category_anchor(category)}\n"
        "    </section>"
    )


def category_sections_html() -> str:
    return "\n".join(category_section(category) for category in CATEGORY_ORDER)


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return slug or "implementation-plan"


def html_document(
    *,
    title: str,
    plan_path: Path,
    notes_path: Path,
    roots: Roots,
    git_sha: str,
    git_branch: str,
    session_id: str,
    timestamp: str,
) -> str:
    safe_title = html_escape(title)
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:\">
  <title>{safe_title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f8fb;
      --surface: #ffffff;
      --surface-muted: #f0f4f8;
      --text: #172033;
      --muted: #5d6b82;
      --line: #d8e0ea;
      --accent: #126b5d;
      --accent-strong: #0a4f46;
      --shadow: 0 20px 60px rgba(23, 32, 51, 0.09);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: linear-gradient(180deg, rgba(18, 107, 93, 0.08), transparent 320px), var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, \"Segoe UI\", sans-serif;
      line-height: 1.58;
    }}
    .page {{ width: min(1120px, calc(100% - 32px)); margin: 0 auto; padding: 48px 0 64px; }}
    .hero {{
      padding: 34px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }}
    .eyebrow {{
      margin: 0 0 8px;
      color: var(--accent-strong);
      font-size: 0.78rem;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    h1, h2, h3 {{ line-height: 1.2; }}
    h1 {{ margin: 0; max-width: 900px; font-size: 3rem; line-height: 1; letter-spacing: 0; }}
    h2 {{ margin: 36px 0 18px; font-size: 1.35rem; }}
    h3 {{ margin: 0 0 12px; color: var(--accent-strong); }}
    .summary-text {{ margin: 12px 0 0; max-width: 760px; color: var(--muted); }}
    .meta-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 28px; }}
    .meta-card {{
      margin: 0;
      padding: 14px 16px;
      background: var(--surface-muted);
      border: 1px solid var(--line);
      border-radius: 8px;
      min-width: 0;
    }}
    .meta-card dt, .meta-card dd {{ display: block; }}
    .meta-card dt {{
      margin-bottom: 4px;
      color: var(--muted);
      font-size: 0.76rem;
      font-weight: 750;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .meta-card dd {{ margin: 0; overflow-wrap: anywhere; font-weight: 650; }}
    .entry-section {{ position: relative; margin-top: 32px; padding-left: 20px; }}
    .entry-section:not(:has(.entry)) {{ display: none; }}
    .entry-section::before {{
      content: \"\";
      position: absolute;
      top: 52px;
      bottom: 8px;
      left: 5px;
      width: 2px;
      background: var(--line);
    }}
    .entry {{
      position: relative;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px 20px;
      margin: 14px 0;
      box-shadow: 0 8px 26px rgba(23, 32, 51, 0.05);
    }}
    .entry::before {{
      content: \"\";
      position: absolute;
      top: 24px;
      left: -20px;
      width: 12px;
      height: 12px;
      background: var(--accent);
      border: 3px solid var(--bg);
      border-radius: 999px;
    }}
    dl {{ display: grid; grid-template-columns: 180px minmax(0, 1fr); gap: 8px 16px; margin: 0; }}
    dt {{ font-weight: 700; color: var(--muted); }}
    dd {{ margin: 0; overflow-wrap: anywhere; }}
    code {{ padding: 0.1em 0.35em; background: var(--surface-muted); border: 1px solid var(--line); border-radius: 6px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.92em; }}
    @media (max-width: 820px) {{
      .page {{ width: min(100% - 20px, 1120px); padding: 20px 0 40px; }}
      .hero {{ padding: 22px; }}
      .meta-grid {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 2rem; }}
      dl {{ grid-template-columns: 1fr; }}
      .entry-section {{ padding-left: 16px; }}
      .entry {{ padding: 16px; }}
    }}
  </style>
</head>
<body>
  <main class=\"page\" data-implementation-notes=\"true\">
    <header class=\"hero\">
      <p class=\"eyebrow\">Implementation Notes</p>
      <h1>{safe_title}</h1>
      <p class=\"summary-text\">Running implementation notes for an approved plan. Content is sanitized before persistence.</p>
      <dl class=\"meta-grid\" aria-label=\"Implementation metadata\">
        <div class=\"meta-card\"><dt>Plan</dt><dd><code>{html_escape(plan_path)}</code></dd></div>
        <div class=\"meta-card\"><dt>Notes</dt><dd><code>{html_escape(notes_path)}</code></dd></div>
        <div class=\"meta-card\"><dt>Status</dt><dd>active</dd></div>
        <div class=\"meta-card\"><dt>Canonical repo root</dt><dd><code>{html_escape(roots.primary_repo_root)}</code></dd></div>
        <div class=\"meta-card\"><dt>Active worktree root</dt><dd><code>{html_escape(roots.active_worktree_root)}</code></dd></div>
        <div class=\"meta-card\"><dt>Session id</dt><dd><code>{html_escape(session_id)}</code></dd></div>
        <div class=\"meta-card\"><dt>Git branch</dt><dd><code>{html_escape(git_branch)}</code></dd></div>
        <div class=\"meta-card\"><dt>Git SHA</dt><dd><code>{html_escape(git_sha)}</code></dd></div>
        <div class=\"meta-card\"><dt>Implementation start</dt><dd><time datetime=\"{html_escape(timestamp)}\">{html_escape(timestamp)}</time></dd></div>
      </dl>
    </header>
    <section aria-labelledby=\"timeline-heading\">
      <h2 id=\"timeline-heading\">Timeline</h2>
      <article class=\"entry\" data-entry-kind=\"initial\">
        <h3>Implementation Started</h3>
        <dl>
          <dt>Timestamp</dt><dd><time datetime=\"{html_escape(timestamp)}\">{html_escape(timestamp)}</time></dd>
          <dt>Category</dt><dd>summary</dd>
          <dt>Decision</dt><dd>Create implementation notes for the approved plan before code changes.</dd>
          <dt>Reason</dt><dd>The workflow requires decision traceability during implementation.</dd>
          <dt>Impact</dt><dd>Subsequent meaningful decisions should be appended as timestamped entries.</dd>
          <dt>Related files</dt><dd><code>{html_escape(plan_path.name)}</code></dd>
          <dt>Status</dt><dd>active</dd>
        </dl>
      </article>
    </section>
{category_sections_html()}
    <!-- IMPLEMENTATION_NOTES_APPEND_ANCHOR -->
  </main>
</body>
</html>
"""


def section_for_category(category: str) -> str:
    return CATEGORY_LABELS[category]


def entry_html(
    *,
    category: str,
    decision: str,
    reason: str,
    impact: str,
    related_files: Iterable[str],
    status: str,
    timestamp: str,
) -> str:
    if category not in ALLOWED_CATEGORIES:
        raise ImplementationNotesError(f"invalid category: {category}")
    related = ", ".join(html_escape(item) for item in related_files if item) or "n/a"
    return f"""
    <article class=\"entry\" data-entry-kind=\"{html_escape(category)}\">
      <dl>
        <dt>Timestamp</dt><dd><time datetime=\"{html_escape(timestamp)}\">{html_escape(timestamp)}</time></dd>
        <dt>Category</dt><dd>{html_escape(category)}</dd>
        <dt>Decision</dt><dd>{html_escape(decision)}</dd>
        <dt>Reason</dt><dd>{html_escape(reason)}</dd>
        <dt>Impact</dt><dd>{html_escape(impact)}</dd>
        <dt>Related files</dt><dd>{related}</dd>
        <dt>Status</dt><dd>{html_escape(status)}</dd>
      </dl>
    </article>
"""


ENTRY_RE = re.compile(r"\n    <article class=\"entry\" data-entry-kind=\"(?P<category>[^\"]+)\">.*?\n    </article>\n", re.DOTALL)


def strip_redundant_entry_heading(entry: str, category: str) -> str:
    label = re.escape(section_for_category(category))
    return re.sub(rf"\n      <h3>{label}</h3>", "", entry)


def ensure_category_anchors(text: str) -> str:
    for category in CATEGORY_ORDER:
        marker = category_anchor(category)
        if marker in text:
            continue
        old_section = (
            f'    <section aria-labelledby="{CATEGORY_HEADING_IDS[category]}">'
            f'<h2 id="{CATEGORY_HEADING_IDS[category]}">{section_for_category(category)}</h2></section>'
        )
        if old_section in text:
            text = text.replace(old_section, category_section(category))
            continue
        global_marker = GLOBAL_APPEND_ANCHOR
        if global_marker in text:
            text = text.replace(global_marker, category_section(category) + "\n" + global_marker, 1)
    return text


def ensure_current_styles(text: str) -> str:
    h2_style = "    h2 { margin-top: 32px; padding-bottom: 6px; border-bottom: 1px solid #d1d5db; }\n"
    if ".entry-section { margin-top:" not in text and h2_style in text:
        text = text.replace(h2_style, h2_style + "    .entry-section { margin-top: 28px; }\n", 1)
    entry_section_style = "    .entry-section { margin-top: 28px; }\n"
    if ".entry-section:not(:has(.entry))" not in text and entry_section_style in text:
        text = text.replace(entry_section_style, entry_section_style + "    .entry-section:not(:has(.entry)) { display: none; }\n", 1)
    return text


def migrate_legacy_entries_to_sections(text: str) -> str:
    text = ensure_current_styles(text)
    if all(category_anchor(category) in text for category in CATEGORY_ORDER):
        return text

    entries_by_category: dict[str, list[str]] = {category: [] for category in CATEGORY_ORDER}

    def remove_grouped_entry(match: re.Match[str]) -> str:
        category = match.group("category")
        if category not in entries_by_category:
            return match.group(0)
        entries_by_category[category].append(strip_redundant_entry_heading(match.group(0), category))
        return "\n"

    text = ENTRY_RE.sub(remove_grouped_entry, text)
    text = ensure_category_anchors(text)
    for category, entries in entries_by_category.items():
        if not entries:
            continue
        marker = category_anchor(category)
        text = text.replace(marker, "".join(entries) + marker, 1)
    return text


def append_entry(notes_path: Path, entry: str, category: str) -> None:
    text = notes_path.read_text(encoding="utf-8")
    text = migrate_legacy_entries_to_sections(text)
    marker = category_anchor(category)
    if marker not in text:
        marker = GLOBAL_APPEND_ANCHOR
    if marker not in text:
        raise ImplementationNotesError("implementation notes append anchor not found")
    notes_path.write_text(text.replace(marker, entry + marker), encoding="utf-8")


def valid_non_initial_entries(text: str) -> list[ParsedEntry]:
    ensure_not_red("implementation notes file", text)
    parser = NotesHTMLParser()
    parser.feed(text)
    if not parser.has_main:
        raise ImplementationNotesError("implementation notes document is missing the notes main marker")
    if not parser.has_csp:
        raise ImplementationNotesError("implementation notes document is missing the restrictive CSP")
    for category in CATEGORY_ORDER:
        if parser.section_counts.get(category) != 1:
            raise ImplementationNotesError(f"implementation notes document must contain exactly one {category} section")
        if parser.anchor_sections.get(category) != category:
            raise ImplementationNotesError(f"implementation notes {category} anchor is outside its matching section")

    valid: list[ParsedEntry] = []
    for entry in parser.entries:
        if entry.category == "initial":
            continue
        if entry.category not in ALLOWED_CATEGORIES:
            raise ImplementationNotesError(f"implementation notes document contains an unknown entry category: {entry.category}")
        if entry.section != entry.category:
            raise ImplementationNotesError(f"implementation notes {entry.category} entry is outside its matching section")
        required = ("Timestamp", "Category", "Decision", "Reason", "Impact", "Related files", "Status")
        missing = [field for field in required if not entry.fields.get(field)]
        if missing:
            raise ImplementationNotesError(f"implementation notes {entry.category} entry is missing required fields: {', '.join(missing)}")
        if entry.fields.get("Category") != entry.category:
            raise ImplementationNotesError("implementation notes entry category field does not match its data-entry-kind")
        if entry.category != "summary":
            valid.append(entry)
    return valid


def notes_has_non_initial_entry(notes_path: Path) -> bool:
    if not notes_path.exists():
        return False
    text = notes_path.read_text(encoding="utf-8", errors="replace")
    return bool(valid_non_initial_entries(text))


def infer_title(plan_path: Path) -> str:
    for line in plan_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped.removeprefix("# ").strip()
    return plan_path.stem
