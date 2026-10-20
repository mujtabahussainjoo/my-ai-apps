"""Unit tests for RAG document loaders and validation (TASK-016)."""

from __future__ import annotations

import pytest

from ecommerce_support.core.exceptions import (
    DocumentTooLargeError,
    IngestionError,
    UnsupportedDocumentTypeError,
)
from ecommerce_support.rag.loaders import (
    DEFAULT_MAX_DOCUMENT_BYTES,
    DocumentType,
    detect_document_type,
    load_document,
)


def _build_pdf(text: str) -> bytes:
    """Build a minimal single-page PDF containing ``text`` (no external tooling)."""
    content = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += b"trailer\n<< /Size " + str(len(objects) + 1).encode() + b" /Root 1 0 R >>\n"
    out += b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF\n"
    return bytes(out)


# --- type detection ---------------------------------------------------------


def test_detect_from_media_type() -> None:
    assert detect_document_type(media_type="application/pdf", filename=None) is DocumentType.PDF


def test_detect_ignores_media_type_parameters() -> None:
    assert (
        detect_document_type(media_type="text/plain; charset=utf-8", filename=None)
        is DocumentType.TEXT
    )


def test_detect_falls_back_to_extension() -> None:
    assert (
        detect_document_type(media_type="application/octet-stream", filename="policy.MD")
        is DocumentType.MARKDOWN
    )


def test_detect_unknown_raises() -> None:
    with pytest.raises(UnsupportedDocumentTypeError) as excinfo:
        detect_document_type(media_type="application/zip", filename="archive.zip")
    assert excinfo.value.details["filename"] == "archive.zip"


# --- loading ----------------------------------------------------------------


def test_load_plain_text_normalized() -> None:
    doc = load_document(source="s", data=b"Hello   world\r\n\r\n\r\nBye", filename="a.txt")
    assert doc.document_type is DocumentType.TEXT
    assert doc.media_type == "text/plain"
    assert doc.text == "Hello world\n\nBye"
    assert doc.byte_size == len(b"Hello   world\r\n\r\n\r\nBye")
    assert doc.filename == "a.txt"


def test_load_markdown_strips_syntax() -> None:
    doc = load_document(
        source="s",
        data=b"# Returns\n\nSee [policy](https://x) for **details**.",
        filename="returns.md",
    )
    assert doc.document_type is DocumentType.MARKDOWN
    assert doc.media_type == "text/markdown"
    assert doc.text == "Returns\n\nSee policy for details."


def test_load_html_extracts_visible_text_and_drops_scripts() -> None:
    html = (
        b"<html><head><title>t</title><style>.x{}</style></head>"
        b"<body><h1>Returns</h1><p>Within 30 days.</p>"
        b"<script>alert('x')</script><noscript>off</noscript></body></html>"
    )
    doc = load_document(source="s", data=html, filename="returns.html")
    assert doc.document_type is DocumentType.HTML
    assert "Returns" in doc.text
    assert "Within 30 days." in doc.text
    assert "alert" not in doc.text
    assert "off" not in doc.text


def test_load_html_decodes_entities() -> None:
    doc = load_document(source="s", data=b"<p>Tom &amp; Jerry &lt;3</p>", filename="x.htm")
    assert doc.text == "Tom & Jerry <3"


def test_load_pdf_extracts_text() -> None:
    doc = load_document(source="s", data=_build_pdf("Hello PDF world"), filename="doc.pdf")
    assert doc.document_type is DocumentType.PDF
    assert doc.media_type == "application/pdf"
    assert doc.text == "Hello PDF world"


def test_corrupt_pdf_raises_ingestion_error() -> None:
    with pytest.raises(IngestionError) as excinfo:
        load_document(source="s", data=b"%PDF-1.4 not really a pdf", filename="doc.pdf")
    assert excinfo.value.details["error_type"]


def test_explicit_media_type_wins_over_extension() -> None:
    doc = load_document(
        source="s",
        data=b"# Heading",
        media_type="text/plain",
        filename="looks-like.md",
    )
    assert doc.document_type is DocumentType.TEXT
    assert doc.text == "# Heading"


# --- validation -------------------------------------------------------------


def test_empty_document_rejected() -> None:
    with pytest.raises(IngestionError):
        load_document(source="s", data=b"", filename="a.txt")


def test_oversized_document_rejected() -> None:
    with pytest.raises(DocumentTooLargeError) as excinfo:
        load_document(source="s", data=b"x" * 11, filename="a.txt", max_bytes=10)
    assert excinfo.value.details == {"source": "s", "byte_size": 11, "max_bytes": 10}


def test_size_checked_before_parsing() -> None:
    # Unsupported type + oversized: size error is raised first (no parsing attempted).
    with pytest.raises(DocumentTooLargeError):
        load_document(source="s", data=b"x" * 11, filename="bad.zip", max_bytes=10)


def test_whitespace_only_document_rejected() -> None:
    with pytest.raises(IngestionError):
        load_document(source="s", data=b"   \n\t  ", filename="a.txt")


def test_allowed_types_allowlist_enforced() -> None:
    with pytest.raises(UnsupportedDocumentTypeError) as excinfo:
        load_document(
            source="s",
            data=b"hi",
            filename="a.txt",
            allowed_types=frozenset({DocumentType.PDF}),
        )
    assert excinfo.value.details["document_type"] == "text"


def test_allowed_types_permits_supported_type() -> None:
    doc = load_document(
        source="s",
        data=b"hi",
        filename="a.txt",
        allowed_types=frozenset({DocumentType.TEXT}),
    )
    assert doc.text == "hi"


def test_default_max_size_constant() -> None:
    assert DEFAULT_MAX_DOCUMENT_BYTES == 10 * 1024 * 1024
