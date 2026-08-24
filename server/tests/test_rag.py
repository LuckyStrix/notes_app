from types import SimpleNamespace

from app.services.rag import (
    build_citations_payload,
    build_context_block,
    confidence_bucket,
    extract_cited_ordinals,
    format_timestamp,
)


def make_chunk(**overrides):
    defaults = dict(id="chunk-1", content="some content", start_time=None, end_time=None, page_start=None, page_end=None)
    return SimpleNamespace(**{**defaults, **overrides})


def make_note(**overrides):
    defaults = dict(id="note-1", title="My Note")
    return SimpleNamespace(**{**defaults, **overrides})


def test_extract_cited_ordinals_finds_all_distinct_markers():
    assert extract_cited_ordinals("See [1] and [3], not [1] again") == {1, 3}


def test_extract_cited_ordinals_empty_when_no_markers():
    assert extract_cited_ordinals("no citations here") == set()


def test_confidence_bucket_thresholds():
    assert confidence_bucket(0.9) == "high"
    assert confidence_bucket(0.55) == "high"
    assert confidence_bucket(0.54) == "medium"
    assert confidence_bucket(0.45) == "medium"
    assert confidence_bucket(0.1) == "low"


def test_format_timestamp():
    assert format_timestamp(0) == "0:00"
    assert format_timestamp(65) == "1:05"
    assert format_timestamp(3661) == "61:01"


def test_build_context_block_empty_rows():
    assert build_context_block([]) == "(no matching notes found)"


def test_build_context_block_labels_audio_chunk_with_timestamp():
    rows = [(make_chunk(start_time=125.0, content="hello"), make_note(title="Lecture 1"), 0.8)]
    block = build_context_block(rows)
    assert "[1] Lecture 1 @ 2:05" in block
    assert "hello" in block


def test_build_context_block_labels_document_chunk_with_page_range():
    rows = [(make_chunk(page_start=2, page_end=4), make_note(title="Report"), 0.8)]
    block = build_context_block(rows)
    assert "[1] Report (p. 2-4)" in block


def test_build_context_block_collapses_single_page_range():
    rows = [(make_chunk(page_start=3, page_end=3), make_note(title="Report"), 0.8)]
    block = build_context_block(rows)
    assert "[1] Report (p. 3)" in block
    assert "3-3" not in block


def test_build_citations_payload_only_includes_ordinals_actually_cited():
    rows = [
        (make_chunk(id="c1", content="a" * 300), make_note(id="n1", title="A"), 0.9),
        (make_chunk(id="c2", content="b"), make_note(id="n2", title="B"), 0.4),
    ]
    citations = build_citations_payload("Some claim [1].", rows)
    assert len(citations) == 1
    assert citations[0]["ordinal"] == 1
    assert citations[0]["note_id"] == "n1"
    assert citations[0]["confidence"] == "high"
    assert citations[0]["quote"] == "a" * 280  # quote is truncated to 280 chars


def test_build_citations_payload_empty_when_no_markers_used():
    rows = [(make_chunk(), make_note(), 0.9)]
    assert build_citations_payload("no markers here", rows) == []
