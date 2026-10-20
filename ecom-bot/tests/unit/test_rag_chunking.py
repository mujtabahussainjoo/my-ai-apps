"""Unit tests for deterministic chunking and content hashing (TASK-017)."""

from __future__ import annotations

import pytest

from ecommerce_support.rag.chunking import (
    ChunkDraft,
    Section,
    chunk_text,
    estimate_tokens,
    split_sections,
)
from ecommerce_support.rag.hashing import content_hash

# --- content hashing --------------------------------------------------------


def test_content_hash_is_deterministic() -> None:
    assert content_hash("hello") == content_hash("hello")


def test_content_hash_matches_str_and_bytes() -> None:
    assert content_hash("hello") == content_hash(b"hello")


def test_content_hash_differs_by_content() -> None:
    assert content_hash("hello") != content_hash("hello ")


def test_content_hash_rejects_other_types() -> None:
    with pytest.raises(TypeError):
        content_hash(123)  # type: ignore[arg-type]


def test_content_hash_is_sha256_length() -> None:
    assert len(content_hash("x")) == 64


# --- token estimation -------------------------------------------------------


def test_estimate_tokens_never_below_one() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens("a") == 1


def test_estimate_tokens_scales_with_length() -> None:
    assert estimate_tokens("abcd" * 25) == 25  # 100 chars / 4


# --- section splitting ------------------------------------------------------


def test_split_sections_detects_short_headings() -> None:
    text = "Return Policy\n\nItems may be returned within 30 days.\n\nShipping\n\nFlat rate."
    sections = split_sections(text)
    assert [section.title for section in sections] == ["Return Policy", "Shipping"]
    assert sections[0].content.startswith("Return Policy")
    assert "You may" not in sections[0].content


def test_split_sections_keeps_prose_without_headings() -> None:
    sections = split_sections("This is one sentence. It continues here.")
    assert len(sections) == 1
    assert sections[0].title is None
    assert sections[0].content == "This is one sentence. It continues here."


def test_split_sections_treats_terminated_line_as_body() -> None:
    sections = split_sections("Returns are accepted within 30 days.")
    assert sections[0].title is None


def test_split_sections_blank_input_yields_nothing() -> None:
    assert split_sections("   \n\n  ") == []


def test_split_sections_heading_without_body_is_kept() -> None:
    sections = split_sections("Warranty\n\nShipping\n\nWe ship fast.")
    assert [section.title for section in sections] == ["Warranty", "Shipping"]
    assert sections[0].content == "Warranty"


# --- chunk sizing -----------------------------------------------------------


def test_chunk_short_text_is_single_chunk() -> None:
    drafts = chunk_text("Small policy text.", chunk_size=1000, chunk_overlap=150)
    assert len(drafts) == 1
    assert drafts[0].index == 0
    assert drafts[0].content == "Small policy text."


def test_chunk_empty_text_yields_nothing() -> None:
    assert chunk_text("   ", chunk_size=100, chunk_overlap=10) == []


def test_chunk_long_text_respects_size_and_overlaps() -> None:
    sentence = "The quick brown fox jumps over the lazy dog. "
    text = sentence * 40
    drafts = chunk_text(text, chunk_size=200, chunk_overlap=40)
    assert len(drafts) > 1
    assert all(len(draft.content) <= 200 for draft in drafts)
    assert [draft.index for draft in drafts] == list(range(len(drafts)))
    overlap = drafts[0].content[-40:]
    assert overlap in drafts[1].content


def test_chunk_indices_are_sequential_across_sections() -> None:
    text = (
        "Returns\n\n"
        + ("return policy details " * 30)
        + "\n\nShipping\n\n"
        + ("shipping details " * 30)
    )
    drafts = chunk_text(text, chunk_size=150, chunk_overlap=20)
    assert [draft.index for draft in drafts] == list(range(len(drafts)))


def test_chunk_section_title_is_propagated() -> None:
    text = "Returns\n\n" + ("return policy details " * 30)
    drafts = chunk_text(text, chunk_size=200, chunk_overlap=20)
    assert drafts
    assert all(draft.section_title == "Returns" for draft in drafts)


def test_chunk_default_section_title_used_when_no_heading() -> None:
    drafts = chunk_text(
        "just some body text without a heading",
        chunk_size=200,
        chunk_overlap=0,
        default_section_title="Policy",
    )
    assert drafts[0].section_title == "Policy"


def test_chunk_deduplicates_identical_content() -> None:
    paragraph = "This exact paragraph appears twice in the document body."
    text = f"Notice\n\n{paragraph}\n\nNotice\n\n{paragraph}"
    drafts = chunk_text(text, chunk_size=1000, chunk_overlap=50)
    assert len(drafts) == 1
    assert drafts[0].content.endswith(paragraph)


def test_chunk_hash_and_token_count_populated() -> None:
    drafts = chunk_text("A policy sentence.", chunk_size=1000, chunk_overlap=0)
    draft = drafts[0]
    assert isinstance(draft, ChunkDraft)
    assert draft.content_hash == content_hash("A policy sentence.")
    assert draft.token_count == estimate_tokens("A policy sentence.")


@pytest.mark.parametrize(
    ("size", "overlap"),
    [(0, 0), (-5, 0), (100, -1), (100, 100), (100, 150)],
)
def test_chunk_rejects_invalid_window(size: int, overlap: int) -> None:
    with pytest.raises(ValueError, match="chunk"):
        chunk_text("some text", chunk_size=size, chunk_overlap=overlap)


def test_section_schema_requires_content() -> None:
    with pytest.raises(ValueError):
        Section(title="Empty", content="")
