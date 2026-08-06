from __future__ import annotations

import re
from pathlib import Path


FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def clean_markdown(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = FRONTMATTER_RE.sub("", text)
    text = HTML_COMMENT_RE.sub("\n", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def parse_markdown_sections(markdown: str, default_heading: str) -> list[dict[str, object]]:
    cleaned = clean_markdown(markdown)
    sections: list[dict[str, object]] = []
    current_heading = default_heading
    current_level = 1
    buffer: list[str] = []

    def flush() -> None:
        content = "\n".join(buffer).strip()
        if content:
            sections.append(
                {
                    "heading_text": current_heading,
                    "heading_level": current_level,
                    "content": content,
                }
            )

    for line in cleaned.splitlines():
        match = HEADING_RE.match(line.strip())
        if match:
            flush()
            buffer = []
            current_level = len(match.group(1))
            current_heading = match.group(2).strip()
            buffer.append(line.strip())
        else:
            buffer.append(line)
    flush()

    if not sections and cleaned:
        sections.append({"heading_text": default_heading, "heading_level": 1, "content": cleaned})
    return sections


def chunk_text(text: str, max_chars: int = 1200, overlap: int = 160) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        window = text[start:end]
        cut = max(window.rfind("\n\n"), window.rfind("。"), window.rfind("；"))
        if cut > max_chars * 0.55:
            end = start + cut + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks


def summarize(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def keywords(text: str) -> list[str]:
    terms = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", text)
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        lowered = term.lower()
        if lowered not in seen:
            result.append(term)
            seen.add(lowered)
    return result
