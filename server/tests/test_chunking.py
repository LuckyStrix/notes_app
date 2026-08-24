from types import SimpleNamespace

from app.services.chunking import chunk_document_pages, chunk_segments, chunk_text


def test_chunk_text_empty_input():
    assert chunk_text("") == []


def test_chunk_text_single_chunk_when_under_target():
    text = " ".join(f"word{i}" for i in range(10))
    chunks = chunk_text(text, target_words=375, overlap_words=40)
    assert chunks == [text]


def test_chunk_text_splits_with_configured_overlap():
    words = [f"w{i}" for i in range(100)]
    text = " ".join(words)
    chunks = chunk_text(text, target_words=30, overlap_words=10)
    assert len(chunks) > 1
    assert chunks[0].split()[-10:] == chunks[1].split()[:10]


def test_chunk_text_covers_every_word_without_gaps():
    words = [f"w{i}" for i in range(100)]
    text = " ".join(words)
    chunks = chunk_text(text, target_words=30, overlap_words=10)
    covered = {w for c in chunks for w in c.split()}
    assert covered == set(words)


def make_segment(id_, start, end, text):
    return SimpleNamespace(id=id_, start_time=start, end_time=end, text=text)


def test_chunk_segments_empty_input():
    assert chunk_segments([]) == []


def test_chunk_segments_never_splits_a_single_segment():
    segments = [make_segment(0, 0.0, 1.0, "a b c")]
    chunks = chunk_segments(segments, target_words=100)
    assert len(chunks) == 1
    assert chunks[0]["text"] == "a b c"


def test_chunk_segments_groups_until_target_reached():
    # 10 segments of 5 words each, target 12 -> first chunk closes once it
    # hits/exceeds 12 words, i.e. after 3 segments (15 words).
    segments = [make_segment(i, float(i), float(i + 1), "word word word word word") for i in range(10)]
    chunks = chunk_segments(segments, target_words=12)
    assert chunks[0]["segment_id_start"] == 0
    assert chunks[0]["segment_id_end"] == 2
    assert chunks[0]["start_time"] == 0.0
    assert chunks[0]["end_time"] == 3.0


def test_chunk_document_pages_no_markers_falls_back_to_plain_chunking():
    text = "just plain text with no page markers"
    chunks = chunk_document_pages(text, target_words=100, overlap_words=10)
    assert len(chunks) == 1
    assert chunks[0]["page_start"] is None
    assert chunks[0]["page_end"] is None


def test_chunk_document_pages_tracks_page_range_spanned_by_a_chunk():
    body = "--- Page 1 ---\n" + " ".join(["a"] * 5) + "\n\n--- Page 2 ---\n" + " ".join(["b"] * 5)
    chunks = chunk_document_pages(body, target_words=100, overlap_words=0)
    assert len(chunks) == 1
    assert chunks[0]["page_start"] == 1
    assert chunks[0]["page_end"] == 2


def test_chunk_document_pages_splits_within_a_single_page():
    body = "--- Page 1 ---\n" + " ".join(["a"] * 5)
    chunks = chunk_document_pages(body, target_words=3, overlap_words=1)
    assert len(chunks) > 1
    assert all(c["page_start"] == 1 and c["page_end"] == 1 for c in chunks)
