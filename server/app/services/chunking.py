"""Chunking for RAG embedding. Word counts are a rough token proxy (~0.75
words/token in English) -- exact tokenization varies by model, and precision
here doesn't matter much since chunk boundaries just need to be "about right".
"""
import re

TARGET_WORDS = 375  # ~500 tokens
OVERLAP_WORDS = 40  # ~50 tokens

PAGE_MARKER_RE = re.compile(r"--- Page (\d+) ---\n?")


def chunk_text(text: str, target_words: int = TARGET_WORDS, overlap_words: int = OVERLAP_WORDS) -> list[str]:
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    while start < len(words):
        end = min(start + target_words, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = end - overlap_words
    return chunks


def chunk_segments(segments: list, target_words: int = TARGET_WORDS) -> list[dict]:
    """Groups whole transcript segments together until ~target_words is
    reached. Never splits a segment -- each chunk's start/end time and segment
    id range come straight from Whisper's own boundaries, which is what makes
    citations timestamp-precise.
    """
    if not segments:
        return []

    chunks = []
    current_texts: list[str] = []
    current_words = 0
    first_seg = None
    last_seg = None

    for seg in segments:
        if first_seg is None:
            first_seg = seg
        current_texts.append(seg.text)
        current_words += len(seg.text.split())
        last_seg = seg

        if current_words >= target_words:
            chunks.append(
                {
                    "text": " ".join(current_texts),
                    "start_time": first_seg.start_time,
                    "end_time": last_seg.end_time,
                    "segment_id_start": first_seg.id,
                    "segment_id_end": last_seg.id,
                }
            )
            current_texts = []
            current_words = 0
            first_seg = None

    if current_texts:
        chunks.append(
            {
                "text": " ".join(current_texts),
                "start_time": first_seg.start_time,
                "end_time": last_seg.end_time,
                "segment_id_start": first_seg.id,
                "segment_id_end": last_seg.id,
            }
        )

    return chunks


def chunk_document_pages(body: str, target_words: int = TARGET_WORDS, overlap_words: int = OVERLAP_WORDS) -> list[dict]:
    """Like chunk_text, but for a document body containing '--- Page N ---'
    markers (inserted by extract_document.py's PDF extraction): strips the
    markers from what actually gets embedded, and tracks which page(s) each
    resulting chunk's words came from -- the document-body analogue of how
    chunk_segments() tracks transcript timestamps.
    """
    matches = list(PAGE_MARKER_RE.finditer(body))
    if not matches:
        return [{"text": t, "page_start": None, "page_end": None} for t in chunk_text(body, target_words, overlap_words)]

    words_with_page: list[tuple[str, int]] = []
    for i, m in enumerate(matches):
        page_num = int(m.group(1))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        for w in body[start:end].split():
            words_with_page.append((w, page_num))

    if not words_with_page:
        return []

    chunks = []
    start = 0
    while start < len(words_with_page):
        end = min(start + target_words, len(words_with_page))
        window = words_with_page[start:end]
        chunks.append(
            {
                "text": " ".join(w for w, _ in window),
                "page_start": window[0][1],
                "page_end": window[-1][1],
            }
        )
        if end == len(words_with_page):
            break
        start = end - overlap_words
    return chunks
