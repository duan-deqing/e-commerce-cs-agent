"""Markdown 语义分块：标题优先切分 + 固定窗口 + 句边界。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings


@dataclass
class Chunk:
    doc_id: str
    title: str
    source: str
    text: str
    metadata: dict


def _split_by_headings(content: str) -> list[tuple[str, str]]:
    parts: list[tuple[str, str]] = []
    current_title = "untitled"
    buf: list[str] = []
    for line in content.splitlines():
        if re.match(r"^#{1,3}\s+", line):
            if buf:
                parts.append((current_title, "\n".join(buf).strip()))
                buf = []
            current_title = line.lstrip("#").strip()
        else:
            buf.append(line)
    if buf:
        parts.append((current_title, "\n".join(buf).strip()))
    return [(t, b) for t, b in parts if b]


def _split_windows(text: str, size: int, overlap: int) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= size:
        return [text] if text else []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        # 尽量在句号处切断
        if end < len(text):
            window = text[start:end]
            cut = max(window.rfind("。"), window.rfind("！"), window.rfind("？"), window.rfind("\n"))
            if cut > size * 0.5:
                end = start + cut + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks


def chunk_file(path: Path, chunk_size: int | None = None, overlap: int | None = None) -> list[Chunk]:
    chunk_size = chunk_size or settings.chunk_size
    overlap = overlap if overlap is not None else settings.chunk_overlap
    raw = path.read_text(encoding="utf-8")
    title_match = re.search(r"^#\s+(.+)$", raw, re.M)
    doc_title = title_match.group(1).strip() if title_match else path.stem
    doc_id = path.stem
    out: list[Chunk] = []
    for si, (section_title, body) in enumerate(_split_by_headings(raw)):
        pieces = _split_windows(body, chunk_size, overlap)
        for i, piece in enumerate(pieces):
            out.append(
                Chunk(
                    doc_id=f"{doc_id}#s{si}c{i}",
                    title=f"{doc_title} / {section_title}",
                    source=str(path),
                    text=piece,
                    metadata={
                        "doc_title": doc_title,
                        "section": section_title,
                        "path": str(path),
                        "chunk_index": i,
                    },
                )
            )
    return out


def chunk_directory(directory: Path | None = None) -> list[Chunk]:
    directory = directory or settings.knowledge_path
    files = sorted(directory.rglob("*.md"))
    chunks: list[Chunk] = []
    for f in files:
        chunks.extend(chunk_file(f))
    return chunks
