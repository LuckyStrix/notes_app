"""Turn a note (typed text, document text, or a Whisper transcript) into ordered
*units* that carry their own location, then pack units into size-bounded chunks.

A unit's `label` is how a reader finds it again: "mm:ss" for recordings, "p.N"
for PDF pages, None for plain notes. Chunks keep the first/last label so both
extraction (big chunks) and retrieval (small chunks) can cite precisely.
"""
import re

from . import transcribe

PAGE_RE = re.compile(r"^--- Page (\d+) ---$", re.M)
LINE_SECONDS = 45.0  # how much speech goes under one [mm:ss] marker


def fmt_time(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}" if s < 3600 else f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def source_text(note: dict) -> str | None:
    """The text a note's analysis is based on: None if a recording has no transcript yet, "" if empty."""
    if note["type"] in ("audio", "video"):
        t = transcribe.load(note["id"])
        return t["full_text"] if t else None
    return note["body"] or ""


def _split_long(text: str, limit: int) -> list[str]:
    """Break an over-long paragraph at sentence ends (or hard, as a last resort)."""
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for sent in re.split(r"(?<=[.!?])\s+", text):
        while len(sent) > limit:  # a "sentence" with no punctuation at all
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(sent[:limit])
            sent = sent[limit:]
        if len(cur) + len(sent) + 1 > limit and cur:
            parts.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        parts.append(cur)
    return parts


def units_for(note: dict, max_unit_chars: int = 1500) -> list[dict]:
    if note["type"] in ("audio", "video"):
        t = transcribe.load(note["id"])
        if not t:
            return []
        units, cur, start = [], [], None
        for seg in t["segments"]:
            if start is None:
                start = seg["start"]
            cur.append(seg["text"])
            if seg["end"] - start >= LINE_SECONDS:
                units.append({"text": " ".join(cur), "label": fmt_time(start), "start": start, "page": None})
                cur, start = [], None
        if cur:
            units.append({"text": " ".join(cur), "label": fmt_time(start), "start": start, "page": None})
        return units

    units, page = [], None
    for para in re.split(r"\n\s*\n", note["body"] or ""):
        para = para.strip()
        if not para:
            continue
        m = PAGE_RE.match(para.splitlines()[0].strip())
        if m:
            page = int(m.group(1))
            para = "\n".join(para.splitlines()[1:]).strip()
            if not para:
                continue
        for piece in _split_long(para, max_unit_chars):
            units.append({"text": piece, "label": f"p.{page}" if page else None, "start": None, "page": page})
    return units


def pack(units: list[dict], max_chars: int) -> list[dict]:
    """Greedily pack consecutive units into chunks of about max_chars."""
    chunks, cur, size = [], [], 0
    for u in units:
        if cur and size + len(u["text"]) > max_chars:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(u)
        size += len(u["text"]) + 1
    if cur:
        chunks.append(cur)
    out = []
    for i, c in enumerate(chunks):
        labels = [u["label"] for u in c if u["label"]]
        out.append(
            {
                "index": i,
                "label_start": labels[0] if labels else None,
                "label_end": labels[-1] if labels else None,
                "start": next((u["start"] for u in c if u["start"] is not None), None),
                "page_start": next((u["page"] for u in c if u["page"]), None),
                "page_end": next((u["page"] for u in reversed(c) if u["page"]), None),
                "text": "\n".join(u["text"] for u in c),
                "marked_text": marked(c),
            }
        )
    return out


def marked(units: list[dict]) -> str:
    """Chunk text with location markers ([mm:ss] or [p.N]) where they change."""
    lines, last = [], None
    for u in units:
        if u["label"] and u["label"] != last:
            lines.append(f"[{u['label']}] {u['text']}")
            last = u["label"]
        else:
            lines.append(u["text"])
    return "\n".join(lines)
