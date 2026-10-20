"""Deterministic, structure-aware text chunking for RAG ingestion (TASK-017, FR-030).

The chunker is framework-free and reproducible. It splits a normalized document into
blank-line-separated blocks, promotes short standalone lines to *section headings* (a heuristic
that works well for policy/FAQ docs whose headings are single short lines), then emits windows of
at most ``chunk_size`` characters with ``chunk_overlap`` characters of context carried across
boundaries. Windows prefer paragraph, then sentence, then line boundaries so chunks stay readable.

Defaults (``chunk_size=1000``, ``chunk_overlap=150``) come from ``RagConfig``; identical chunks are
de-duplicated by content hash so repeated boilerplate is stored once per document.
"""

from __future__ import annotations

import math
import re

from pydantic import Field

from ecommerce_support.rag.hashing import content_hash
from ecommerce_support.schemas.common import Schema

_SECTION_SPLIT = re.compile(r"\n{2,}")
_PARAGRAPH = "\n\n"
_SENTENCES = (". ", "! ", "? ", "\n")
_SENTENCE_TERMINATORS = (".", ",", ";", ":")
_HEADING_MAX_CHARS = 80
_HEADING_MAX_WORDS = 12


class Section(Schema):
    """A document section: an optional heading plus its body text."""

    title: str | None = Field(default=None, max_length=300)
    content: str = Field(min_length=1)


class ChunkDraft(Schema):
    """A chunk ready to be persisted (embedding is added later, TASK-018)."""

    index: int = Field(ge=0)
    content: str = Field(min_length=1)
    content_hash: str = Field(min_length=1, max_length=128)
    section_title: str | None = Field(default=None, max_length=300)
    token_count: int = Field(ge=1)


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 characters per token), used for budgeting before embedding."""
    return max(1, math.ceil(len(text) / 4))


def split_sections(text: str) -> list[Section]:
    """Split ``text`` into sections, using short standalone lines as headings.

    Returns an empty list for blank input. A heading with no following body becomes a section
    whose content is the heading text, so no content is dropped.
    """
    blocks = [block.strip() for block in _SECTION_SPLIT.split(text) if block.strip()]
    sections: list[Section] = []
    title: str | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal title, body
        if title is None and not body:
            return
        rendered = "\n\n".join(body).strip()
        content = f"{title}\n\n{rendered}".strip() if title else rendered
        if content:
            sections.append(Section(title=title, content=content))
        title = None
        body = []

    for block in blocks:
        if _looks_like_heading(block):
            flush()
            title = block
        else:
            body.append(block)
    flush()
    return sections


def chunk_text(
    text: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
    default_section_title: str | None = None,
) -> list[ChunkDraft]:
    """Split ``text`` into de-duplicated :class:`ChunkDraft` windows.

    Args:
        text: normalized document text (see :mod:`ecommerce_support.rag.normalization`).
        chunk_size: maximum characters per chunk; must be positive.
        chunk_overlap: characters of context carried across windows; ``0 <= overlap < chunk_size``.
        default_section_title: heading used when a section has no detected title.

    Raises:
        ValueError: ``chunk_size`` is not positive, or ``chunk_overlap`` is out of range.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be >= 0 and < chunk_size")

    text = text.strip()
    if not text:
        return []

    sections = split_sections(text) or [Section(title=default_section_title, content=text)]
    drafts: list[ChunkDraft] = []
    seen: set[str] = set()
    index = 0
    for section in sections:
        title = section.title or default_section_title
        for piece in _split_window(section.content, chunk_size=chunk_size, overlap=chunk_overlap):
            digest = content_hash(piece)
            if digest in seen:
                continue
            seen.add(digest)
            drafts.append(
                ChunkDraft(
                    index=index,
                    content=piece,
                    content_hash=digest,
                    section_title=title,
                    token_count=estimate_tokens(piece),
                )
            )
            index += 1
    return drafts


def _looks_like_heading(block: str) -> bool:
    """Heuristic heading detector: a short, standalone, capitalized, non-sentence line."""
    if "\n" in block or len(block) > _HEADING_MAX_CHARS:
        return False
    if not block or not block[0].isalnum():
        return False
    if block.endswith(_SENTENCE_TERMINATORS):
        return False
    if len(block.split()) > _HEADING_MAX_WORDS:
        return False
    return block[0].isupper()


def _split_window(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    """Split ``text`` into overlapping windows, preferring natural boundaries."""
    total = len(text)
    if total <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < total:
        end = min(start + chunk_size, total)
        if end < total:
            end = _trim_boundary(text, start=start, end=end, chunk_size=chunk_size)
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= total:
            break
        advance = end - overlap
        start = advance if advance > start else end
    return chunks


def _trim_boundary(text: str, *, start: int, end: int, chunk_size: int) -> int:
    """Move ``end`` back to a paragraph/sentence/newline break when one is near enough."""
    minimum = start + max(1, chunk_size // 2)
    window = text[start:end]
    para = window.rfind(_PARAGRAPH)
    if para != -1 and start + para >= minimum:
        return start + para
    for sep in _SENTENCES:
        found = window.rfind(sep)
        if found != -1 and start + found >= minimum:
            return start + found + (0 if sep == "\n" else len(sep))
    return end
