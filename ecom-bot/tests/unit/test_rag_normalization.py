"""Unit tests for RAG text normalization (TASK-016)."""

from __future__ import annotations

import pytest

from ecommerce_support.rag.normalization import markdown_to_text, normalize_text

# --- normalize_text ---------------------------------------------------------


def test_collapses_internal_whitespace_and_trims_lines() -> None:
    assert normalize_text("a   b\t c  \n\n\n") == "a b c"


def test_unifies_line_endings() -> None:
    assert normalize_text("a\r\nb\rc") == "a\nb\nc"


def test_folds_unicode_spaces_to_ascii() -> None:
    assert normalize_text("a\u00a0b\u3000c") == "a b c"


def test_applies_nfkc_compatibility_folding() -> None:
    # Full-width digits and the Kelvin sign fold to ASCII equivalents.
    assert normalize_text("\uff11\uff12\uff13") == "123"
    assert normalize_text("\u212a") == "K"


def test_removes_control_characters_but_keeps_newlines() -> None:
    assert normalize_text("a\x00b\x07c\n d\x7f") == "abc\n d"


def test_collapses_runs_of_blank_lines() -> None:
    assert normalize_text("a\n\n\n\n\nb") == "a\n\nb"


def test_strips_leading_and_trailing_whitespace() -> None:
    assert normalize_text("\n\n  hello  \n\n") == "hello"


def test_empty_string_stays_empty() -> None:
    assert normalize_text("") == ""
    assert normalize_text("   \n\t ") == ""


def test_normalization_is_idempotent() -> None:
    messy = "  Header\r\n\r\n\r\n  body   text\u00a0 here \x00"
    once = normalize_text(messy)
    assert normalize_text(once) == once


def test_rejects_non_string() -> None:
    with pytest.raises(TypeError):
        normalize_text(b"bytes")  # type: ignore[arg-type]


# --- markdown_to_text -------------------------------------------------------


def test_strips_heading_markers() -> None:
    assert markdown_to_text("# Title") == "Title"
    assert markdown_to_text("### Sub") == "Sub"


def test_strips_emphasis_and_inline_code() -> None:
    assert markdown_to_text("**bold** and *italic*").strip() == "bold and italic"
    assert markdown_to_text("use `code` here").strip() == "use code here"


def test_keeps_link_label_drops_url() -> None:
    assert markdown_to_text("see [docs](https://example.com/x)").strip() == "see docs"


def test_keeps_image_alt_text() -> None:
    assert markdown_to_text("![diagram](img.png)").strip() == "diagram"


def test_strips_list_and_blockquote_markers() -> None:
    text = markdown_to_text("- one\n- two\n\n> quoted")
    assert "- one" not in text
    assert "one" in text and "two" in text and "quoted" in text


def test_removes_code_fences_but_keeps_content() -> None:
    text = markdown_to_text("```python\nprint(1)\n```")
    assert "print(1)" in text
    assert "```" not in text


def test_removes_horizontal_rules() -> None:
    assert markdown_to_text("a\n---\nb") == "a\n\nb"


def test_markdown_rejects_non_string() -> None:
    with pytest.raises(TypeError):
        markdown_to_text(123)  # type: ignore[arg-type]
