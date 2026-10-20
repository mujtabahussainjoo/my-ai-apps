"""Document loading, type/size validation, and text extraction (TASK-016).

Supported formats: Markdown, plain text, PDF, and HTML. Each loader extracts raw text and
hands it to :func:`~ecommerce_support.rag.normalization.normalize_text` (Markdown additionally
runs through :func:`~ecommerce_support.rag.normalization.markdown_to_text`).

Validation happens **before** any parsing so oversized or unsupported uploads are rejected
cheaply and loudly (:class:`DocumentTooLargeError` / :class:`UnsupportedDocumentTypeError`).
No network access and no framework imports; the extracted :class:`LoadedDocument` is a plain
Pydantic contract consumed by the chunker (TASK-017).
"""

from __future__ import annotations

import io
from enum import StrEnum
from pathlib import Path

from bs4 import BeautifulSoup
from pydantic import Field
from pypdf import PdfReader

from ecommerce_support.core.exceptions import (
    DocumentTooLargeError,
    IngestionError,
    UnsupportedDocumentTypeError,
)
from ecommerce_support.rag.normalization import markdown_to_text, normalize_text
from ecommerce_support.schemas.common import Schema

DEFAULT_MAX_DOCUMENT_BYTES = 10 * 1024 * 1024

_HTML_DROP_TAGS = ("script", "style", "noscript", "template", "head", "iframe", "object")


class DocumentType(StrEnum):
    """A supported source document format."""

    MARKDOWN = "markdown"
    TEXT = "text"
    PDF = "pdf"
    HTML = "html"


EXTENSION_TYPES: dict[str, DocumentType] = {
    ".md": DocumentType.MARKDOWN,
    ".markdown": DocumentType.MARKDOWN,
    ".txt": DocumentType.TEXT,
    ".text": DocumentType.TEXT,
    ".pdf": DocumentType.PDF,
    ".html": DocumentType.HTML,
    ".htm": DocumentType.HTML,
}

MEDIA_TYPE_TYPES: dict[str, DocumentType] = {
    "text/markdown": DocumentType.MARKDOWN,
    "text/x-markdown": DocumentType.MARKDOWN,
    "text/plain": DocumentType.TEXT,
    "application/pdf": DocumentType.PDF,
    "application/x-pdf": DocumentType.PDF,
    "text/html": DocumentType.HTML,
    "application/xhtml+xml": DocumentType.HTML,
}

DEFAULT_MEDIA_TYPES: dict[DocumentType, str] = {
    DocumentType.MARKDOWN: "text/markdown",
    DocumentType.TEXT: "text/plain",
    DocumentType.PDF: "application/pdf",
    DocumentType.HTML: "text/html",
}

SUPPORTED_DOCUMENT_TYPES = frozenset(DocumentType)


class LoadedDocument(Schema):
    """A validated, text-extracted, normalized document ready for chunking."""

    source: str = Field(min_length=1, max_length=1000)
    filename: str | None = Field(default=None, max_length=255)
    media_type: str = Field(min_length=1, max_length=100)
    document_type: DocumentType
    byte_size: int = Field(ge=0)
    text: str = Field(min_length=1)


def detect_document_type(*, media_type: str | None, filename: str | None) -> DocumentType:
    """Resolve the document type from an explicit media type, then the filename extension.

    Raises :class:`UnsupportedDocumentTypeError` when neither is recognized.
    """
    if media_type:
        base = media_type.split(";", 1)[0].strip().lower()
        if base in MEDIA_TYPE_TYPES:
            return MEDIA_TYPE_TYPES[base]
    if filename:
        ext = Path(filename).suffix.lower()
        if ext in EXTENSION_TYPES:
            return EXTENSION_TYPES[ext]
    raise UnsupportedDocumentTypeError(
        "Unsupported document type; expected Markdown, text, PDF, or HTML.",
        details={"media_type": media_type, "filename": filename},
    )


def load_document(
    *,
    source: str,
    data: bytes,
    media_type: str | None = None,
    filename: str | None = None,
    max_bytes: int = DEFAULT_MAX_DOCUMENT_BYTES,
    allowed_types: frozenset[DocumentType] | None = None,
) -> LoadedDocument:
    """Validate and extract ``data`` into a normalized :class:`LoadedDocument`.

    Args:
        source: stable identifier/URI for the document (used for versioning upstream).
        data: raw document bytes.
        media_type: declared content type, if any (used before the filename extension).
        filename: original filename, used to infer the type when ``media_type`` is absent.
        max_bytes: maximum accepted size; larger inputs raise :class:`DocumentTooLargeError`.
        allowed_types: optional allowlist; a type outside it is rejected.

    Raises:
        DocumentTooLargeError: ``len(data)`` exceeds ``max_bytes``.
        UnsupportedDocumentTypeError: type cannot be resolved or is not allowed.
        IngestionError: extraction failed or produced no usable text.
    """
    if not data:
        raise IngestionError("Document is empty.", details={"source": source})
    if len(data) > max_bytes:
        raise DocumentTooLargeError(
            f"Document exceeds the maximum size of {max_bytes} bytes.",
            details={"source": source, "byte_size": len(data), "max_bytes": max_bytes},
        )

    document_type = detect_document_type(media_type=media_type, filename=filename)
    if allowed_types is not None and document_type not in allowed_types:
        raise UnsupportedDocumentTypeError(
            "Document type is not permitted by the ingestion policy.",
            details={"source": source, "document_type": document_type.value},
        )

    raw = _extract(document_type, data, source=source)
    text = normalize_text(markdown_to_text(raw) if document_type is DocumentType.MARKDOWN else raw)
    if not text:
        raise IngestionError(
            "Document has no extractable text.",
            details={"source": source, "document_type": document_type.value},
        )

    return LoadedDocument(
        source=source,
        filename=filename,
        media_type=(media_type.split(";", 1)[0].strip().lower() if media_type else None)
        or DEFAULT_MEDIA_TYPES[document_type],
        document_type=document_type,
        byte_size=len(data),
        text=text,
    )


def _extract(document_type: DocumentType, data: bytes, *, source: str) -> str:
    if document_type is DocumentType.PDF:
        return _extract_pdf(data, source=source)
    if document_type is DocumentType.HTML:
        return _extract_html(data)
    # TEXT and MARKDOWN both decode as UTF-8; invalid bytes are replaced, never fatal.
    return data.decode("utf-8", errors="replace")


def _extract_pdf(data: bytes, *, source: str) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise IngestionError(
                "Encrypted PDF documents are not supported.",
                details={"source": source},
            )
        pages = [page.extract_text() or "" for page in reader.pages]
    except IngestionError:
        raise
    except Exception as exc:
        raise IngestionError(
            "Failed to parse PDF document.",
            details={"source": source, "error_type": type(exc).__name__},
        ) from exc
    return "\n\n".join(pages)


def _extract_html(data: bytes) -> str:
    soup = BeautifulSoup(data, "html.parser")
    for tag in soup(_HTML_DROP_TAGS):
        tag.decompose()
    return soup.get_text("\n")
