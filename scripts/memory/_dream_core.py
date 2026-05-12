from __future__ import annotations

import re
import sys
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
            "confidence": self.confidence,
            "hash": self.hash,
            "duplicate_existing": self.duplicate_existing,
            "duplicate_count": self.duplicate_count,
        }


def normalize_candidate(text: str) -> str:
    return PUNCTUATION.sub(" ", text.lower()).strip()


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


def source_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for relative in ("handoffs", "ledgers"):
        base = root / relative
        if base.exists():
            paths.extend(path for path in base.glob("*.md") if path.is_file())
    return sorted(paths, key=lambda path: path.stat().st_mtime, reverse=True)


def collect_sources(root: Path, since_days: int | None, max_items: int) -> tuple[list[SourceItem], list[dict[str, object]]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days) if since_days else None
    sources: list[SourceItem] = []
    skipped: list[dict[str, object]] = []
    for path in source_paths(root):
        if len(sources) + len(skipped) >= max_items:
            break
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
        sources.append(SourceItem(relative_path=str(path.relative_to(root)), text=text, classification=classification))
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
    if len(text) > 220:
        score -= 0.2
    if len(text.split()) < 5 or any(marker in lowered for marker in ("thing", "stuff", "todo")):
        score -= 0.2
    return round(min(0.95, max(0.0, score)), 2)


def extract_candidates(root: Path, sources: list[SourceItem]) -> tuple[list[Candidate], int]:
    layer_text = "\n".join(read_text(root / "layers" / filename) for filename in LAYER_FILES.values())
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
            if source.classification == "YELLOW":
                candidate.classification = "YELLOW"
    duplicate_count = finalize_candidates(grouped.values())
    candidates = sorted(grouped.values(), key=lambda item: (-item.confidence, item.target_layer, item.text.lower()))
    return candidates, duplicate_count


def finalize_candidates(candidates: object) -> int:
    duplicate_count = 0
    for candidate in candidates:
        candidate.duplicate_count = len(candidate.source_paths)
        source_kinds = {path.split("/", 1)[0] for path in candidate.source_paths}
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
