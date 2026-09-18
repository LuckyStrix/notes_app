"""Retrieval index over the raw source text (transcripts, notes, documents).

SQLite file in our own data dir. Each chunk (~1200 chars) stores its location
so answers can cite "note @ 12:34" or "note, p.5". Search fuses two rankings
with reciprocal-rank fusion: dense embeddings (meaning) and FTS5 (exact terms,
names, jargon -- where embeddings alone are weakest).

Incremental: a note is re-embedded only if its source text, the embedding
model, or the chunk size changed.
"""
import hashlib
import re
import sqlite3

import numpy as np

from . import chunking, ollama, store

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks(
  id INTEGER PRIMARY KEY, note_id TEXT, project TEXT, folder TEXT, title TEXT, type TEXT,
  label TEXT, start_sec REAL, text TEXT, embedding BLOB);
CREATE INDEX IF NOT EXISTS chunks_note ON chunks(note_id);
CREATE TABLE IF NOT EXISTS indexed(note_id TEXT PRIMARY KEY, source_hash TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(text, tokenize='porter unicode61');
"""


def connect() -> sqlite3.Connection:
    store.ensure_dirs()
    con = sqlite3.connect(store.INDEX_DB)
    con.executescript(SCHEMA)
    return con


def _normalize(vectors: list[list[float]]) -> np.ndarray:
    m = np.asarray(vectors, dtype=np.float32)
    return m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)


def build(cfg: dict, notes: list[dict], log=print) -> None:
    con = connect()
    embed_model = cfg["models"]["embed"]
    live = {n["id"] for n in notes}
    # Drop index rows for notes that no longer exist in the mirror (derived data only).
    for (nid,) in con.execute("SELECT note_id FROM indexed").fetchall():
        if nid not in live:
            _delete_note(con, nid)

    for note in notes:
        text = chunking.source_text(note)
        if not text or not text.strip():
            continue
        digest = hashlib.sha256(f"{embed_model}\0{cfg['retrieval_chunk_chars']}\0{text}".encode()).hexdigest()
        row = con.execute("SELECT source_hash FROM indexed WHERE note_id=?", (note["id"],)).fetchone()
        if row and row[0] == digest:
            continue
        chunks = chunking.pack(chunking.units_for(note, max_unit_chars=600), cfg["retrieval_chunk_chars"])
        folder = "/".join(note["group_path"])
        header = f"{note['project']} / {folder} / {note['title']}"
        log(f"  indexing {header} ({len(chunks)} chunks)")
        vectors = _normalize(ollama.embed(cfg, [f"search_document: {header}\n{c['text']}" for c in chunks]))

        _delete_note(con, note["id"])
        for c, vec in zip(chunks, vectors):
            cur = con.execute(
                "INSERT INTO chunks(note_id, project, folder, title, type, label, start_sec, text, embedding) VALUES (?,?,?,?,?,?,?,?,?)",
                (note["id"], note["project"], folder, note["title"], note["type"], c["label_start"], c["start"], c["text"], vec.tobytes()),
            )
            con.execute("INSERT INTO chunk_fts(rowid, text) VALUES (?, ?)", (cur.lastrowid, c["text"]))
        con.execute("INSERT OR REPLACE INTO indexed(note_id, source_hash) VALUES (?,?)", (note["id"], digest))
        con.commit()


def _delete_note(con: sqlite3.Connection, note_id: str) -> None:
    ids = [r[0] for r in con.execute("SELECT id FROM chunks WHERE note_id=?", (note_id,))]
    con.executemany("DELETE FROM chunk_fts WHERE rowid=?", [(i,) for i in ids])
    con.execute("DELETE FROM chunks WHERE note_id=?", (note_id,))
    con.execute("DELETE FROM indexed WHERE note_id=?", (note_id,))
    con.commit()


def _fts_query(query: str) -> str | None:
    words = [w for w in re.findall(r"[A-Za-z0-9]+", query) if len(w) > 2]
    return " OR ".join(f'"{w}"' for w in words) or None


def search(cfg: dict, query: str, *, projects: list[str] | None = None, k: int | None = None, pool: int = 50) -> list[dict]:
    k = k or cfg["retrieval_top_k"]
    con = connect()
    where, args = "", []
    if projects:
        where = "WHERE project IN (%s)" % ",".join("?" * len(projects))
        args = list(projects)
    rows = con.execute(f"SELECT id, embedding FROM chunks {where}", args).fetchall()
    if not rows:
        return []
    ids = [r[0] for r in rows]
    matrix = np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
    qvec = _normalize(ollama.embed(cfg, [f"search_query: {query}"]))[0]
    dense = np.argsort(-(matrix @ qvec))[:pool]
    scores: dict[int, float] = {}
    for rank, idx in enumerate(dense):
        scores[ids[idx]] = scores.get(ids[idx], 0) + 1 / (60 + rank)

    fts = _fts_query(query)
    if fts:
        allowed = set(ids)
        rank = 0
        for (rid,) in con.execute("SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH ? ORDER BY rank LIMIT ?", (fts, pool * 4)):
            if rid in allowed:
                scores[rid] = scores.get(rid, 0) + 1 / (60 + rank)
                rank += 1
                if rank >= pool:
                    break

    top = sorted(scores, key=scores.get, reverse=True)[:k]
    out = []
    for cid in top:
        r = con.execute(
            "SELECT note_id, project, folder, title, type, label, start_sec, text FROM chunks WHERE id=?", (cid,)
        ).fetchone()
        out.append(dict(zip(("note_id", "project", "folder", "title", "type", "label", "start_sec", "text"), r)) | {"score": scores[cid]})
    return out
