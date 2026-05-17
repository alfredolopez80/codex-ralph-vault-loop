from __future__ import annotations

import re
import sys
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _memory_common import LAYER_FILES, content_hash, read_text
from classify_learning import classify_learning

SECURITY_DIR = Path(__file__).resolve().parents[1] / "security"
if str(SECURITY_DIR) not in sys.path:
    sys.path.insert(0, str(SECURITY_DIR))

from sensitive_content import public_findings  # noqa: E402


MARKERS = (
    "decision",
    "learned",
    "root cause",
    "validated",
    "fixed",
    "checkpoint",
    "rule",
    "must",
    "should",
    "always",
    "never",
)
L1_MARKERS = ("always", "never", "must", "red", "secret", "security")
L2_MARKERS = ("repo", "project", "migration", "checkpoint", "local convention", "tests/unit")
L3_MARKERS = ("vault", "mivault", "index", "external note")
STRIP_PREFIX = re.compile(r"^\s*(?:[-*]\s+|\d+\.\s+|#{1,6}\s+|>\s+)?")
PUNCTUATION = re.compile(r"[^a-z0-9]+")
DEFAULT_CODEX_MEMORY_HOME = Path("~/.codex/memories").expanduser()
SKIP_PATH_PARTS = (".env", "id_rsa", "id_ed25519")
SKIP_PATH_SUBSTRINGS = ("secrets", "token", "credential", "wallet", "keystore")


@dataclass(frozen=True)
class SourcePath:
    path: Path
    label: str


@dataclass
class SourceItem:
    relative_path: str
    text: str
    classification: str


@dataclass
class Candidate:
    target_layer: str
    classification: str
    text: str
    source_paths: list[str] = field(default_factory=list)
    source_groups: list[str] = field(default_factory=list)
    confidence: float = 0.5
    hash: str = ""
    duplicate_existing: bool = False
    duplicate_count: int = 1

    def public_dict(self) -> dict[str, object]:
        return {
            "target_layer": self.target_layer,
            "classification": self.classification,
            "text": self.text,
            "source_paths": self.source_paths,
            "source_groups": self.source_groups,
            "confidence": self.confidence,
            "hash": self.hash,
            "duplicate_existing": self.duplicate_existing,
            "duplicate_count": self.duplicate_count,
        }


def normalize_candidate(text: str) -> str:
    return PUNCTUATION.sub(" ", text.lower()).strip()


def path_is_sensitive(path: Path) -> bool:
    lowered_parts = [part.lower() for part in path.parts]
    lowered_text = str(path).lower()
    return any(part in lowered_parts for part in SKIP_PATH_PARTS) or any(
        part in lowered_text for part in SKIP_PATH_SUBSTRINGS
    )


def path_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        home = Path.home()
        try:
            return "~/" + str(path.relative_to(home))
        except ValueError:
            return path.name


def source_group(label: str) -> str:
    return label.split("/", 1)[0]


def parse_created_at(text: str) -> datetime | None:
    if not text.startswith("---"):
        return None
    for line in text.splitlines()[1:25]:
        if line.strip() == "---":
            break
        if line.startswith("created_at:"):
            value = line.split(":", 1)[1].strip().strip('"')
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
    return None


def strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    lines = text.splitlines()
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[index + 1 :])
    return text


def iter_markdown_tree(base: Path, label_root: Path, label_prefix: str) -> list[SourcePath]:
    if not base.exists() or path_is_sensitive(base):
        return []
    sources: list[SourcePath] = []
    for path in base.rglob("*.md"):
        if path.is_file() and not path_is_sensitive(path):
            sources.append(SourcePath(path=path, label=f"{label_prefix}/{safe_relative(path, label_root)}"))
    return sources


def codex_memory_sources() -> list[SourcePath]:
    configured = os.environ.get("CODEX_MEMORY_HOME")
    if configured is not None and not configured.strip():
        return []
    root = Path(configured).expanduser() if configured else DEFAULT_CODEX_MEMORY_HOME
    if not root.exists() or path_is_sensitive(root):
        return []
    sources: list[SourcePath] = []
    for path in (root / "MEMORY.md", root / "memory_summary.md"):
        if path.is_file() and not path_is_sensitive(path):
            sources.append(SourcePath(path=path, label=f"codex-memories/{safe_relative(path, root)}"))
    rollout_root = root / "rollout_summaries"
    sources.extend(iter_markdown_tree(rollout_root, root, "codex-memories"))
    return sources


def configured_local_notes_roots() -> list[Path] | None:
    configured = os.environ.get("RALPH_LOCAL_NOTES_ROOTS")
    if configured is None:
        return None
    return [Path(value).expanduser() for value in configured.split(os.pathsep) if value.strip()]


def discover_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return start


def default_local_notes_roots() -> list[Path]:
    roots: list[Path] = []
    cwd = Path.cwd()
    for candidate in (cwd, *cwd.parents):
        notes = candidate / ".local-notes"
        if notes.exists():
            roots.append(notes)
        if (candidate / ".git").exists():
            break

    repo_root = discover_repo_root(cwd)
    repo_name = repo_root.name
    github_root = Path("~/Documents/GitHub").expanduser()
    if github_root.exists():
        roots.append(github_root / repo_name / ".local-notes")
        roots.extend(github_root.glob(f"*/{repo_name}/.local-notes"))
    return roots


def local_notes_sources() -> list[SourcePath]:
    roots = configured_local_notes_roots()
    if roots is None:
        roots = default_local_notes_roots()
    sources: list[SourcePath] = []
    seen: set[str] = set()
    for root in roots:
        if not root.exists() or path_is_sensitive(root):
            continue
        key = path_key(root)
        if key in seen:
            continue
        seen.add(key)
        repo_label = root.parent.name if root.name == ".local-notes" else root.name
        sources.extend(iter_markdown_tree(root, root, f"local-notes/{repo_label}"))
    return sources


def source_paths(root: Path) -> list[SourcePath]:
    paths: list[SourcePath] = []
    for relative in ("handoffs", "ledgers"):
        base = root / relative
        paths.extend(iter_markdown_tree(base, base, relative))
    paths.extend(codex_memory_sources())
    paths.extend(local_notes_sources())
    unique: dict[str, SourcePath] = {}
    for source in paths:
        unique.setdefault(path_key(source.path), source)
    return sorted(unique.values(), key=lambda source: source.path.stat().st_mtime, reverse=True)


def collect_sources(root: Path, since_days: int | None, max_items: int) -> tuple[list[SourceItem], list[dict[str, object]]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days) if since_days else None
    sources: list[SourceItem] = []
    skipped: list[dict[str, object]] = []
    for source_path in source_paths(root):
        if len(sources) + len(skipped) >= max_items:
            break
        path = source_path.path
        text = read_text(path)
        created_at = parse_created_at(text)
        if cutoff and created_at and created_at < cutoff:
            continue
        digest = content_hash(text)
        classification = classify_learning(text)
        if classification == "RED":
            findings = public_findings(text) or [{"kind": "classification", "label": "classified_red", "severity": "RED"}]
            skipped.append({"hash": digest, "reason": "RED", "findings": findings})
            continue
        sources.append(SourceItem(relative_path=source_path.label, text=text, classification=classification))
    return sources, skipped


def candidate_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in strip_frontmatter(text).splitlines():
        line = STRIP_PREFIX.sub("", raw_line).strip()
        if not line or line.startswith("|") or line.startswith("---"):
            continue
        if any(marker in line.lower() for marker in MARKERS):
            lines.append(line)
    return lines


def target_layer(text: str) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in L3_MARKERS):
        return "L3"
    if any(marker in lowered for marker in L2_MARKERS):
        return "L2"
    if any(marker in lowered for marker in L1_MARKERS):
        return "L1"
    return "report-only"


def score_candidate(text: str, source_count: int, source_kinds: set[str]) -> float:
    lowered = text.lower()
    score = 0.5
    if source_count >= 2:
        score += 0.1
    if any(marker in lowered for marker in ("decision", "root cause", "validated")):
        score += 0.1
    if {"handoffs", "ledgers"}.issubset(source_kinds):
        score += 0.1
    if {"codex-memories", "local-notes"}.intersection(source_kinds) and {"handoffs", "ledgers"}.intersection(source_kinds):
        score += 0.05
    if len(text) > 220:
        score -= 0.2
    if len(text.split()) < 5 or any(marker in lowered for marker in ("thing", "stuff", "todo")):
        score -= 0.2
    return round(min(0.95, max(0.0, score)), 2)


def extract_candidates(root: Path, sources: list[SourceItem]) -> tuple[list[Candidate], int]:
    canonical_layers = ("L1", "L2", "L3")
    layer_text = "\n".join(read_text(root / "layers" / LAYER_FILES[layer]) for layer in canonical_layers)
    normalized_layers = normalize_candidate(layer_text)
    grouped: dict[str, Candidate] = {}
    for source in sources:
        for line in candidate_lines(source.text):
            normalized = normalize_candidate(line)
            if not normalized:
                continue
            digest = content_hash(normalized)
            candidate = grouped.get(digest)
            if candidate is None:
                candidate = Candidate(target_layer(line), source.classification, line, hash=digest, duplicate_existing=normalized in normalized_layers)
                grouped[digest] = candidate
            if source.relative_path not in candidate.source_paths:
                candidate.source_paths.append(source.relative_path)
            group = source_group(source.relative_path)
            if group not in candidate.source_groups:
                candidate.source_groups.append(group)
            if source.classification == "YELLOW":
                candidate.classification = "YELLOW"
    duplicate_count = finalize_candidates(grouped.values())
    candidates = sorted(grouped.values(), key=lambda item: (-item.confidence, item.target_layer, item.text.lower()))
    return candidates, duplicate_count


def finalize_candidates(candidates: object) -> int:
    duplicate_count = 0
    for candidate in candidates:
        candidate.duplicate_count = len(candidate.source_paths)
        candidate.source_groups = sorted(candidate.source_groups)
        source_kinds = set(candidate.source_groups)
        candidate.confidence = score_candidate(candidate.text, candidate.duplicate_count, source_kinds)
        if candidate.duplicate_count > 1 or candidate.duplicate_existing:
            duplicate_count += 1
    return duplicate_count


def build_report(root: Path, since_days: int | None, max_items: int, created_at: str) -> dict[str, object]:
    sources, skipped = collect_sources(root, since_days, max_items)
    candidates, duplicate_count = extract_candidates(root, sources)
    return {
        "created_at": created_at,
        "mode": "dry-run",
        "classification": "YELLOW",
        "source_count": len(sources) + len(skipped),
        "safe_source_count": len(sources),
        "red_skipped": len(skipped),
        "duplicate_count": duplicate_count,
        "candidates": [candidate.public_dict() for candidate in candidates],
        "skipped": skipped,
    }
