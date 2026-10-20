"""Text normalization for the RAG ingestion pipeline (TASK-016).

Normalization is deterministic and framework-free. It produces clean, comparable plain text
from extracted document content so chunking and embeddings are stable across sources:

- Unicode NFKC (folds full-width/compatibility characters to canonical forms).
- CRLF/CR line endings unified to LF.
- Exotic Unicode whitespace folded to ASCII space; control characters removed (NUL, C0/C1).
- Runs of spaces/tabs collapsed; trailing whitespace stripped per line.
- Runs of 3+ blank lines collapsed to a single blank line; leading/trailing blank lines trimmed.

Markdown is additionally reduced to readable prose (headings, emphasis, links, code fences) via
:func:`markdown_to_text`. HTML cleaning happens in the loader (BeautifulSoup); the text it yields
is passed through :func:`normalize_text`.
"""

from __future__ import annotations

import re
import unicodedata

# Unicode space separators (NBSP, en/em spaces, ideographic space, …) → ASCII space.
_UNICODE_SPACES = (
    "\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u202f\u205f\u3000"
)

_TRANSLATION: dict[int, str | None] = {ord(ch): " " for ch in _UNICODE_SPACES}
for _code in range(0x20):  # C0 controls except TAB (0x09) and LF (0x0a)
    if _code not in (0x09, 0x0A):
        _TRANSLATION[_code] = None
for _code in (*range(0x7F, 0xA0),):  # DEL and C1 controls
    _TRANSLATION[_code] = None

_MULTI_SPACE = re.compile(r" {2,}")
_MULTI_BLANK = re.compile(r"\n{3,}")

_FENCE = re.compile(r"^```.*$", re.MULTILINE)
_HR = re.compile(r"^ {0,3}([-*_]) *(?:\1 *){2,}$", re.MULTILINE)
_HEADER = re.compile(r"^ {0,3}#{1,6} +", re.MULTILINE)
_BLOCKQUOTE = re.compile(r"^ {0,3}> ?", re.MULTILINE)
_LIST = re.compile(r"^ {0,3}(?:[-*+]|\d+[.)]) +", re.MULTILINE)
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_INLINE_CODE = re.compile(r"`([^`]*)`")
_BOLD_STAR = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_STAR = re.compile(r"\*([^*]+)\*")
_BOLD_UNDERSCORE = re.compile(r"__([^_]+)__")
_ITALIC_UNDERSCORE = re.compile(r"_([^_]+)_")


def normalize_text(text: str) -> str:
    """Return a canonical, whitespace-cleaned form of ``text``.

    Raises ``TypeError`` for non-string input. Empty input yields an empty string; callers
    decide whether that is an error (see :mod:`ecommerce_support.rag.loaders`).
    """
    if not isinstance(text, str):
        raise TypeError("normalize_text expects a str")

    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.translate(_TRANSLATION)
    text = text.replace("\t", " ")

    lines = [_MULTI_SPACE.sub(" ", line).rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _MULTI_BLANK.sub("\n\n", text)
    return text.strip()


def markdown_to_text(markdown: str) -> str:
    """Reduce Markdown to plain prose while keeping the underlying content.

    Strips fence markers, heading/list/quote/hr markers, link/image syntax (keeping the visible
    label), and emphasis/inline-code markers. Code *content* is preserved.
    """
    if not isinstance(markdown, str):
        raise TypeError("markdown_to_text expects a str")

    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    text = _FENCE.sub("", text)
    text = _HR.sub("", text)
    text = _HEADER.sub("", text)
    text = _BLOCKQUOTE.sub("", text)
    text = _LIST.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _BOLD_STAR.sub(r"\1", text)
    text = _ITALIC_STAR.sub(r"\1", text)
    text = _BOLD_UNDERSCORE.sub(r"\1", text)
    text = _ITALIC_UNDERSCORE.sub(r"\1", text)
    return text
