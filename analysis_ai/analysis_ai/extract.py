"""Per-note study cards via chunked map-then-merge.

Map: each ~6000-char chunk of a note (about 9 minutes of a lecture) goes to the
model alone, so it can afford to be thorough about that stretch. Merge: items
from all chunks are combined deterministically (no LLM pass that could silently
drop things); only the note's title and overall summary are written by the
model, from the per-chunk summaries.

Cards are cached by a hash of (source text, prompt version, model), so re-runs
only redo notes whose text, prompt or model changed.
"""
import hashlib
import re
import time
from datetime import datetime, timezone

from . import chunking, ollama, store

PROMPT_VERSION = "2"
SHORT_NOTE_CHARS = 300  # below this, the note itself is the card -- nothing to compress

_STR = {"type": "string"}


def _list_of(props: dict) -> dict:
    return {"type": "array", "items": {"type": "object", "properties": props, "required": list(props)}}


CHUNK_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "2-3 sentences on what this part covers"},
        "topics": _list_of({"name": _STR, "explanation": _STR, "at": _STR}),
        "key_terms": _list_of({"term": _STR, "definition": _STR}),
        "formulas_and_rules": _list_of({"statement": _STR, "context": _STR}),
        "examples": _list_of({"description": _STR, "takeaway": _STR}),
        "instructor_emphasis": {"type": "array", "items": _STR},
        "logistics": {"type": "array", "items": _STR},
    },
    "required": ["summary", "topics", "key_terms", "formulas_and_rules", "examples", "instructor_emphasis", "logistics"],
}

TITLE_SCHEMA = {
    "type": "object",
    "properties": {"title": _STR, "summary": {"type": "string", "description": "5-8 sentences"}},
    "required": ["title", "summary"],
}

SOURCE_KIND = {
    "audio": "an auto-generated transcript of a recorded class session",
    "video": "an auto-generated transcript of a recorded class session",
    "document": "text extracted from a document (syllabus, slides, or reading)",
    "text": "the student's own typed notes or a pasted transcript",
}

CHUNK_PROMPT = """You are building a study card for a student. The material below is {kind}.
Course: {project}. Folder: {folder}. Note title: "{title}". This is part {part} of {parts} of the source, so it may begin or end mid-thought.

Rules:
- Extract only substantive course content. Ignore small talk, jokes, personal anecdotes, tangents unrelated to the course, and classroom management chatter -- except exams, deadlines, assignments and readings, which go in "logistics".
- Be thorough about THIS part: include every distinct concept, definition, formula or rule, worked example, and named theory/person/term the material actually covers. Prefer the source's own definitions, numbers and examples over generic textbook statements.
- "instructor_emphasis": anything the instructor or author flags as important, testable, or a common mistake ("this will be on the exam", "students always get this wrong"). Empty list if none.
- The text may contain transcription errors or shorthand. Use context to interpret it, but never invent facts, numbers or terms the material does not support.
- "at": the [mm:ss] or [p.N] marker nearest where the topic begins, written without brackets; empty string if the material has no markers.
- If a section has nothing in it, return an empty list rather than filling it with guesses.

MATERIAL:
{text}
"""

TITLE_PROMPT = """Below are summaries of consecutive parts of one source ("{title}", course {project}).
Write a short descriptive title for what it covers, and a 5-8 sentence overall summary of its substantive content.

{parts}
"""


def source_hash(text: str, model: str) -> str:
    return hashlib.sha256(f"{PROMPT_VERSION}\0{model}\0{text}".encode()).hexdigest()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _merge(partials: list[dict], chunks: list[dict]) -> dict:
    merged = {"topics": [], "key_terms": [], "formulas_and_rules": [], "examples": [], "instructor_emphasis": [], "logistics": []}
    seen: dict[str, dict[str, int]] = {k: {} for k in merged}

    for part, chunk in zip(partials, chunks):
        where = chunk["label_start"]

        def located(claimed) -> str | None:
            # Trust a model-claimed location only if that exact marker exists in this
            # chunk; small models happily invent "00:00" on notes that have no markers.
            claimed = (claimed or "").strip("[] ")
            return claimed if claimed and f"[{claimed}]" in chunk["marked_text"] else where

        for key, items in merged.items():
            for item in part.get(key, []):
                if isinstance(item, str):
                    ident, entry = _norm(item), {"text": item, "at": where}
                else:
                    ident = _norm(item.get({"topics": "name", "key_terms": "term", "formulas_and_rules": "statement",
                                            "examples": "description"}[key], ""))
                    entry = {**item, "at": located(item.get("at"))}
                if not ident:
                    continue
                if ident in seen[key]:
                    # Same key term seen again: keep the fuller definition.
                    existing = merged[key][seen[key][ident]]
                    if key == "key_terms" and len(entry.get("definition", "")) > len(existing.get("definition", "")):
                        merged[key][seen[key][ident]] = entry
                    continue
                seen[key][ident] = len(merged[key])
                merged[key].append(entry)
    return merged


def extract_note(cfg: dict, note: dict, *, force: bool = False, log=print) -> str:
    """Returns a status string: cached | done | short | search-only | no-source | empty."""
    text = chunking.source_text(note)
    if text is None:
        return "no-source"  # media note not transcribed yet
    if not text.strip():
        return "empty"
    model = cfg["models"]["extract"]
    path = store.CARDS / f"{note['id']}.json"
    digest = source_hash(text, model)
    existing = store.read_json(path)
    if existing and existing["meta"]["source_hash"] == digest and not force:
        return "cached"
    if len(text) > cfg["max_extract_chars"]:
        return "search-only"

    ident = {k: note[k] for k in ("id", "project", "group_path", "title", "type")}
    meta = {"source_hash": digest, "prompt_version": PROMPT_VERSION, "model": model,
            "generated_at": datetime.now(timezone.utc).isoformat()}

    if len(text.strip()) < SHORT_NOTE_CHARS:
        store.write_json(path, {"note": ident, "meta": meta, "short": True, "summary": text.strip(), "chunks": []})
        return "short"

    started = time.time()
    chunks = chunking.pack(chunking.units_for(note), cfg["text_chunk_chars"])
    partials = []
    for c in chunks:
        log(f"    chunk {c['index'] + 1}/{len(chunks)} ({len(c['text'])} chars)")
        prompt = CHUNK_PROMPT.format(
            kind=SOURCE_KIND[note["type"]], project=note["project"], folder="/".join(note["group_path"]) or "(none)",
            title=note["title"], part=c["index"] + 1, parts=len(chunks), text=c["marked_text"],
        )
        partials.append(ollama.generate_json(cfg, "extract", prompt, CHUNK_SCHEMA))

    merged = _merge(partials, chunks)
    summaries = "\n".join(f"Part {i + 1}: {p.get('summary', '')}" for i, p in enumerate(partials))
    head = ollama.generate_json(
        cfg, "extract", TITLE_PROMPT.format(title=note["title"], project=note["project"], parts=summaries), TITLE_SCHEMA
    )
    meta["seconds"] = round(time.time() - started)
    store.write_json(path, {
        "note": ident, "meta": meta, "short": False, "title": head["title"], "summary": head["summary"], **merged,
        "chunks": [{"index": c["index"], "label_start": c["label_start"], "label_end": c["label_end"],
                    "page_start": c["page_start"], "page_end": c["page_end"], "summary": p.get("summary", "")}
                   for c, p in zip(chunks, partials)],
    })
    return "done"


def extract_all(cfg: dict, notes: list[dict], *, only: str | None = None, project: str | None = None,
                force: bool = False) -> None:
    store.ensure_dirs()
    targets = [n for n in notes if (only is None or n["id"].startswith(only))
               and (project is None or project.lower() in n["project"].lower())]
    counts: dict[str, int] = {}
    for i, note in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {note['project']} / {'/'.join(note['group_path'])} / {note['title']} ({note['type']})", flush=True)
        try:
            status = extract_note(cfg, note, force=force, log=lambda m: print(m, flush=True))
        except Exception as exc:  # noqa: BLE001 -- one bad note must not stop an overnight run
            status = f"FAILED: {exc}"
        counts[status.split(":")[0]] = counts.get(status.split(":")[0], 0) + 1
        print(f"    -> {status}", flush=True)
    print("summary:", counts, flush=True)
