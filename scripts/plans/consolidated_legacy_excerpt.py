from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from implementation_notes_lib import ensure_not_red


class PlainTextHTMLParser(HTMLParser):
    SKIP_TAGS = {"head", "script", "style", "svg", "math", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.pre_blocks: list[str] = []
        self._skip_depth = 0
        self._pre_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if normalized == "pre" and self._skip_depth == 0:
            self._pre_parts = []

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if normalized == "pre" and self._pre_parts is not None:
            raw = "".join(self._pre_parts).strip()
            if raw:
                self.pre_blocks.append(raw)
            self._pre_parts = None

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._pre_parts is not None:
            self._pre_parts.append(data)
            return
        stripped = data.strip()
        if stripped:
            self.parts.append(stripped)

    def text(self) -> str:
        return " ".join(" ".join(self.parts).split())


def plain_text_html(text: str) -> tuple[str, list[str]]:
    parser = PlainTextHTMLParser()
    parser.feed(text)
    parser.close()
    return parser.text(), parser.pre_blocks


def best_legacy_excerpt_text(text: str) -> str:
    extracted, pre_blocks = plain_text_html(text)
    candidates: list[str] = []
    for raw_block in pre_blocks:
        source = unescape(raw_block).strip()
        lower = source.lower()
        if "<html" not in lower and "<!doctype" not in lower and "implementation notes" not in lower:
            continue
        candidate, _ = plain_text_html(source)
        if candidate:
            candidates.append(candidate)
    if candidates:
        return max(candidates, key=len)
    return extracted


def legacy_excerpt(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    ensure_not_red(f"legacy implementation notes file {path}", text)
    return best_legacy_excerpt_text(text)
