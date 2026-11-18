"""Chunking: sizes, topic boundaries, overlap and page tracking."""

import re

import pytest

from app.ingestion.chunker import chunk_sections, estimate_tokens
from app.ingestion.extractors.base import Section


def sentences(n: int, prefix: str = "Fact") -> str:
    return " ".join(f"{prefix} number {i} is written here in full." for i in range(n))


def test_small_topics_become_one_chunk_each():
    sections = [
        Section("Annual leave is 25 days.", ("Leave", "Annual")),
        Section("Carry over up to 5 days.", ("Leave", "Annual")),
        Section("Sick leave is 10 days.", ("Leave", "Sick")),
    ]
    chunks = chunk_sections(sections)
    assert [c.heading_path for c in chunks] == [("Leave", "Annual"), ("Leave", "Sick")]
    assert chunks[0].text == "Annual leave is 25 days.\n\nCarry over up to 5 days."


def test_chunks_never_mix_topics_even_when_small():
    sections = [Section(f"Text {i}.", (f"Heading {i}",)) for i in range(5)]
    chunks = chunk_sections(sections, target_tokens=500)
    assert len(chunks) == 5


def test_long_section_is_split_within_target_size():
    sections = [Section(sentences(300), ("Big",))]  # ~3,000 tokens
    chunks = chunk_sections(sections, target_tokens=200, overlap_tokens=30)
    assert len(chunks) > 10
    assert all(c.token_count <= 200 for c in chunks)
    # Cuts land between sentences, never mid-sentence.
    assert all(c.text.endswith(".") for c in chunks)


def test_consecutive_chunks_overlap():
    chunks = chunk_sections(
        [Section(sentences(100), ("Big",))], target_tokens=200, overlap_tokens=30
    )
    for previous, current in zip(chunks, chunks[1:], strict=False):
        first_sentence = current.text.split(". ")[0] + "."
        assert first_sentence in previous.text, "next chunk should start with the end of the last"
        overlap = current.text[: current.text.index(first_sentence) + len(first_sentence)]
        assert estimate_tokens(overlap) <= 30


def test_no_overlap_across_topics():
    sections = [Section(sentences(60, "Alpha"), ("A",)), Section(sentences(5, "Beta"), ("B",))]
    chunks = chunk_sections(sections, target_tokens=200, overlap_tokens=30)
    beta = [c for c in chunks if c.heading_path == ("B",)]
    assert len(beta) == 1 and "Alpha" not in beta[0].text


def test_all_content_is_kept():
    text = sentences(120)
    chunks = chunk_sections([Section(text, ("Big",))], target_tokens=150, overlap_tokens=20)
    found = set()
    for c in chunks:
        found |= set(re.findall(r"Fact number (\d+) ", c.text))
    assert found == {str(i) for i in range(120)}


def test_page_ranges():
    sections = [
        Section(sentences(30, "One"), ("H",), page=1),
        Section(sentences(30, "Two"), ("H",), page=2),
        Section(sentences(30, "Three"), ("H",), page=3, page_end=4),
    ]
    chunks = chunk_sections(sections, target_tokens=1000, overlap_tokens=50)
    assert len(chunks) == 1
    assert (chunks[0].page_start, chunks[0].page_end) == (1, 4)

    small = chunk_sections(sections, target_tokens=350, overlap_tokens=50)
    assert small[0].page_start == 1
    assert small[-1].page_end == 4


def test_structure_inside_a_section_is_preserved():
    table = "City | Cap\nLondon | $250\nElsewhere | $180"
    chunks = chunk_sections([Section(table, ("Hotels",))])
    assert chunks[0].text == table


def test_giant_word_is_hard_cut():
    blob = "x" * 5000
    chunks = chunk_sections([Section(blob, ("Data",))], target_tokens=200, overlap_tokens=20)
    assert "".join(c.text for c in chunks).count("x") >= 5000
    assert all(c.token_count <= 200 for c in chunks)


def test_overlap_must_be_smaller_than_target():
    with pytest.raises(ValueError):
        chunk_sections([Section("x", ())], target_tokens=100, overlap_tokens=100)
