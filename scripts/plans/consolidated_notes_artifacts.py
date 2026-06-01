from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from implementation_notes_lib import (
    CATEGORY_LABELS,
    IMPLEMENTATION_NOTES_SUFFIX,
    ImplementationNotesError,
    NotesHTMLParser,
    ensure_not_red,
    html_escape,
    valid_non_initial_entries,
)


CONSOLIDATED_HTML_NAME = "implementation-notes-consolidated.html"
CONSOLIDATED_MD_NAME = "implementation-notes-consolidated.md"
HTML_ANCHOR = "    <!-- CONSOLIDATED_IMPLEMENTATION_NOTES_APPEND_ANCHOR -->"
MD_ANCHOR = "<!-- CONSOLIDATED_IMPLEMENTATION_NOTES_MD_APPEND_ANCHOR -->"
HTML_KEY_RE = re.compile(r'data-consolidated-key="([^"]+)"')
MD_KEY_RE = re.compile(r"<!-- consolidated-key: ([0-9a-f]{64}) -->")
SENSITIVE_NAME_RE = re.compile(r"(?i)(^\.env(?:\.|$)|secret|token|credential|wallet|keystore|cookies?|id_rsa|id_ed25519|\.pem$|\.key$)")


@dataclass(frozen=True)
class ConsolidatedEntry:
    category: str
    timestamp: str
    decision: str
    reason: str
    impact: str
    related_files: str
    status: str


@dataclass(frozen=True)
class ConsolidatedPlanSection:
    slug: str
    plan_path: Path
    notes_path: Path
    schema: str
    status: str
    source_sha256: str
    entries: list[ConsolidatedEntry]
    legacy_excerpt: str = ""


@dataclass(frozen=True)
class ConsolidatedItem:
    key: str
    section: ConsolidatedPlanSection
    category: str
    timestamp: str
    title: str
    rows: tuple[tuple[str, str], ...]


class PlainTextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if stripped:
            self.parts.append(stripped)

    def text(self) -> str:
        return " ".join(" ".join(self.parts).split())


def current_entries(path: Path) -> list[ConsolidatedEntry]:
    text = path.read_text(encoding="utf-8", errors="replace")
    ensure_not_red(f"implementation notes file {path}", text)
    valid_non_initial_entries(text)
    parser = NotesHTMLParser()
    parser.feed(text)
    entries: list[ConsolidatedEntry] = []
    for entry in parser.entries:
        if entry.category == "initial":
            continue
        entries.append(
            ConsolidatedEntry(
                category=entry.category,
                timestamp=entry.fields.get("Timestamp", ""),
                decision=entry.fields.get("Decision", ""),
                reason=entry.fields.get("Reason", ""),
                impact=entry.fields.get("Impact", ""),
                related_files=entry.fields.get("Related files", ""),
                status=entry.fields.get("Status", ""),
            )
        )
    return entries


def legacy_excerpt(path: Path, limit: int = 6000) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    ensure_not_red(f"legacy implementation notes file {path}", text)
    parser = PlainTextHTMLParser()
    parser.feed(text)
    extracted = parser.text()
    if len(extracted) <= limit:
        return extracted
    return extracted[:limit].rstrip() + "..."


def item_key(parts: list[str]) -> str:
    payload = "\0".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def consolidated_items(sections: list[ConsolidatedPlanSection]) -> list[ConsolidatedItem]:
    items: list[ConsolidatedItem] = []
    for section in sections:
        if section.schema == "legacy":
            rows = common_rows(section) + (("Excerpt", section.legacy_excerpt),)
            key = item_key([section.slug, "legacy", section.source_sha256, section.legacy_excerpt])
            items.append(ConsolidatedItem(key, section, "legacy", "", "Legacy Notes", rows))
            continue
        for entry in section.entries:
            rows = common_rows(section) + (
                ("Timestamp", entry.timestamp or "n/a"),
                ("Category", entry.category),
                ("Decision", entry.decision or "n/a"),
                ("Reason", entry.reason or "n/a"),
                ("Impact", entry.impact or "n/a"),
                ("Related files", entry.related_files or "n/a"),
                ("Entry status", entry.status or "n/a"),
            )
            key = item_key([section.slug, entry.category, entry.timestamp, entry.decision, entry.reason, entry.impact, entry.related_files, entry.status])
            title = CATEGORY_LABELS.get(entry.category, entry.category)
            items.append(ConsolidatedItem(key, section, entry.category, entry.timestamp, title, rows))
    return sorted(items, key=lambda item: (item.section.slug, item.timestamp, item.category, item.key))


def common_rows(section: ConsolidatedPlanSection) -> tuple[tuple[str, str], ...]:
    return (
        ("Plan", str(section.plan_path)),
        ("Notes", section.notes_path.name),
        ("Plan status", section.status),
        ("Schema", section.schema),
        ("Source SHA256", section.source_sha256),
    )


def plans_artifact_path(primary_root: Path, explicit_path: str | None, default_name: str) -> Path:
    plans_root = primary_root / ".ralph" / "plans"
    primary = primary_root.resolve(strict=False)
    root = plans_root.resolve(strict=False)
    try:
        root.relative_to(primary)
    except ValueError as exc:
        raise ImplementationNotesError(f"primary .ralph/plans resolves outside primary repo: {plans_root}") from exc
    if explicit_path:
        explicit = Path(explicit_path).expanduser()
        candidate = explicit if explicit.is_absolute() else plans_root / explicit
    else:
        candidate = plans_root / default_name
    if any(part == ".." for part in candidate.parts):
        raise ImplementationNotesError(f"path traversal is not allowed: {candidate}")
    if any(SENSITIVE_NAME_RE.search(part) for part in candidate.parts):
        raise ImplementationNotesError(f"sensitive filename is not allowed: {candidate}")
    if candidate.is_symlink() and candidate.resolve().parent != root:
        raise ImplementationNotesError(f"symlink target escapes primary .ralph/plans: {candidate}")
    resolved = candidate.resolve(strict=False)
    if resolved.parent != root:
        raise ImplementationNotesError(f"consolidated artifact must live in primary .ralph/plans: {candidate}")
    if resolved.name.endswith(IMPLEMENTATION_NOTES_SUFFIX):
        raise ImplementationNotesError("consolidated artifact must not look like a per-plan implementation notes file")
    return resolved


def resolve_consolidated_paths(primary_root: Path, html_path: str | None, md_path: str | None) -> tuple[Path, Path]:
    resolved_html = plans_artifact_path(primary_root, html_path, CONSOLIDATED_HTML_NAME)
    resolved_md = plans_artifact_path(primary_root, md_path, CONSOLIDATED_MD_NAME)
    if resolved_html == resolved_md:
        raise ImplementationNotesError("consolidated HTML and Markdown artifacts must be distinct files")
    return resolved_html, resolved_md


def existing_keys(path: Path, pattern: re.Pattern[str]) -> set[str]:
    if not path.exists():
        return set()
    return set(pattern.findall(path.read_text(encoding="utf-8", errors="replace")))


def planned_append_counts(sections: list[ConsolidatedPlanSection], html_path: Path, md_path: Path) -> dict[str, int]:
    items = consolidated_items(sections)
    html_keys = existing_keys(html_path, HTML_KEY_RE)
    md_keys = existing_keys(md_path, MD_KEY_RE)
    return {
        "items": len(items),
        "html_append": sum(1 for item in items if item.key not in html_keys),
        "md_append": sum(1 for item in items if item.key not in md_keys),
    }


def append_consolidated_artifacts(primary_root: Path, html_path: Path, md_path: Path, sections: list[ConsolidatedPlanSection]) -> dict[str, int]:
    validate_consolidated_targets(html_path, md_path)
    items = consolidated_items(sections)
    html_text, html_appended, write_html = prepared_artifact(html_path, html_shell(primary_root), HTML_ANCHOR, HTML_KEY_RE, items, render_html_item, "HTML")
    md_text, md_appended, write_md = prepared_artifact(md_path, markdown_shell(primary_root), MD_ANCHOR, MD_KEY_RE, items, render_markdown_item, "Markdown")
    if write_html:
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(html_text, encoding="utf-8")
    if write_md:
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md_text, encoding="utf-8")
    return {"items": len(items), "html_append": html_appended, "md_append": md_appended}


def validate_consolidated_targets(html_path: Path, md_path: Path) -> None:
    if html_path.resolve(strict=False) == md_path.resolve(strict=False):
        raise ImplementationNotesError("consolidated HTML and Markdown artifacts must be distinct files")
    if html_path.exists() and HTML_ANCHOR not in html_path.read_text(encoding="utf-8", errors="replace"):
        raise ImplementationNotesError(f"consolidated HTML append anchor not found: {html_path}")
    if md_path.exists() and MD_ANCHOR not in md_path.read_text(encoding="utf-8", errors="replace"):
        raise ImplementationNotesError(f"consolidated Markdown append anchor not found: {md_path}")


def prepared_artifact(path: Path, shell: str, anchor: str, key_re: re.Pattern[str], items: list[ConsolidatedItem], render_item, label: str) -> tuple[str, int, bool]:
    exists = path.exists()
    text = path.read_text(encoding="utf-8") if exists else shell
    if anchor not in text:
        raise ImplementationNotesError(f"consolidated {label} append anchor not found: {path}")
    seen = set(key_re.findall(text))
    missing = [item for item in items if item.key not in seen]
    if not missing and exists:
        return text, 0, False
    addition = "".join(render_item(item) for item in missing)
    ensure_not_red(f"consolidated implementation notes {label} append", addition)
    return text.replace(anchor, addition + anchor, 1), len(missing), True


def html_shell(primary_root: Path) -> str:
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">
  <title>Consolidated Implementation Notes</title>
  <style>
    :root {{ color-scheme: light; --bg: #f7f8fb; --surface: #fff; --surface-muted: #eef3f8; --text: #172033; --muted: #627086; --line: #d8e0ea; --accent: #126b5d; --accent-warm: #8a5a12; --shadow: 0 18px 54px rgba(23, 32, 51, 0.08); }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: linear-gradient(180deg, rgba(18, 107, 93, 0.07), transparent 300px), var(--bg); color: var(--text); font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, \"Segoe UI\", sans-serif; line-height: 1.58; }}
    .page {{ width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 44px 0 64px; }}
    .hero, .entry {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow); }}
    .hero {{ padding: 34px; }}
    .entry {{ margin-top: 18px; padding: 20px; border-left: 4px solid var(--accent); }}
    .entry[data-entry-kind=\"legacy\"] {{ border-left-color: var(--accent-warm); }}
    .eyebrow {{ margin: 0 0 8px; color: var(--accent); font-size: 0.76rem; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; }}
    h1, h2, h3 {{ line-height: 1.2; letter-spacing: 0; }}
    h1 {{ margin: 0; max-width: 920px; font-size: 2.7rem; }}
    h2 {{ margin: 0 0 12px; font-size: 1.5rem; }}
    h3 {{ margin: 0 0 12px; color: var(--accent); }}
    p, dd {{ overflow-wrap: anywhere; }}
    .summary-text {{ margin: 12px 0 0; max-width: 780px; color: var(--muted); }}
    .meta-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 24px; }}
    .meta-card {{ margin: 0; min-width: 0; padding: 12px 14px; background: var(--surface-muted); border: 1px solid var(--line); border-radius: 8px; }}
    .meta-card dt {{ margin-bottom: 4px; color: var(--muted); font-size: 0.74rem; font-weight: 780; letter-spacing: 0.06em; text-transform: uppercase; }}
    .meta-card dd {{ margin: 0; overflow-wrap: anywhere; font-weight: 650; }}
    dl {{ display: grid; grid-template-columns: 170px minmax(0, 1fr); gap: 8px 16px; margin: 0; }}
    dt {{ color: var(--muted); font-weight: 700; }}
    dd {{ margin: 0; }}
    code {{ padding: 0.1em 0.35em; background: var(--surface); border: 1px solid var(--line); border-radius: 6px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.92em; }}
    @media (max-width: 900px) {{ .page {{ width: min(100% - 20px, 1180px); padding: 20px 0 40px; }} .hero, .entry {{ padding: 20px; }} h1 {{ font-size: 2rem; }} .meta-grid {{ grid-template-columns: 1fr; }} dl {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main class=\"page\" data-consolidated-implementation-notes=\"true\">
    <header class=\"hero\">
      <p class=\"eyebrow\">Implementation Notes</p>
      <h1>Consolidated Implementation Notes</h1>
      <p class=\"summary-text\">Append-only view of implementation decisions consolidated from per-plan notes.</p>
      <dl class=\"meta-grid\" aria-label=\"Consolidation metadata\">
        <div class=\"meta-card\"><dt>Canonical repo root</dt><dd><code>{html_escape(primary_root)}</code></dd></div>
        <div class=\"meta-card\"><dt>Mode</dt><dd>append ordered</dd></div>
        <div class=\"meta-card\"><dt>Source files</dt><dd>per-plan HTML notes</dd></div>
      </dl>
    </header>
{HTML_ANCHOR}
  </main>
</body>
</html>
"""


def markdown_shell(primary_root: Path) -> str:
    return f"""# Consolidated Implementation Notes

Canonical repo root: `{markdown_escape(primary_root)}`

This file is append-only. It consolidates per-plan implementation notes without replacing the source HTML notes.

{MD_ANCHOR}
"""


def render_html_item(item: ConsolidatedItem) -> str:
    rows = "\n".join(f"          <dt>{html_escape(label)}</dt><dd>{html_escape(value) or 'n/a'}</dd>" for label, value in item.rows)
    return f"""
    <article class=\"entry\" data-consolidated-key=\"{item.key}\" data-plan-slug=\"{html_escape(item.section.slug)}\" data-entry-kind=\"{html_escape(item.category)}\">
      <p class=\"eyebrow\">{html_escape(item.section.schema)} notes</p>
      <h2>{html_escape(item.section.slug)}</h2>
      <h3>{html_escape(item.title)}</h3>
      <dl>
{rows}
      </dl>
    </article>
"""


def render_markdown_item(item: ConsolidatedItem) -> str:
    lines = [
        f"\n<!-- consolidated-key: {item.key} -->",
        f"## {markdown_escape(item.section.slug)}",
        "",
        f"### {markdown_escape(item.title)}",
        "",
    ]
    lines.extend(f"- **{markdown_escape(label)}:** {markdown_escape(value or 'n/a')}" for label, value in item.rows)
    return "\n".join(lines) + "\n"


def markdown_escape(value: object) -> str:
    escaped = html_escape("" if value is None else str(value)).replace("\\", "\\\\")
    for char in "`*_[]()!":
        escaped = escaped.replace(char, f"\\{char}")
    return escaped
