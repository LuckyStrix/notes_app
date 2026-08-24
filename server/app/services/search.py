import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.embeddings import embed_texts
from app.models.embedding import EmbeddingChunk
from app.models.note import Note
from app.services.chunking import PAGE_MARKER_RE

SEMANTIC_OVERFETCH = 50  # more than we'll return, so we can dedupe to one row per note


async def update_note_search_vector(db: AsyncSession, note: Note, extra_text: str | None = None) -> None:
    """Recomputes note.search_vector from title + body + any extra text (e.g.
    a transcript's full_text for audio/video notes, which have no body).
    Caller is responsible for commit/flush.
    """
    body_for_search = PAGE_MARKER_RE.sub("", note.body or "")
    combined = " ".join(filter(None, [note.title, body_for_search, extra_text]))
    await db.execute(
        update(Note).where(Note.id == note.id).values(search_vector=func.to_tsvector("english", combined))
    )


async def search_literal(
    db: AsyncSession, project_id: uuid.UUID, query: str, group_id: uuid.UUID | None, limit: int = 20
) -> list[dict]:
    tsquery = func.plainto_tsquery("english", query)
    rank = func.ts_rank(Note.search_vector, tsquery)
    # StartSel/StopSel empty -- no <b> markup, so the frontend can render the
    # snippet as plain text instead of needing dangerouslySetInnerHTML.
    snippet = func.ts_headline(
        "english", func.coalesce(Note.body, Note.title), tsquery, 'StartSel="", StopSel="", MaxWords=35, MinWords=15'
    )

    stmt = (
        select(Note, rank.label("score"), snippet.label("snippet"))
        .where(Note.project_id == project_id, Note.search_vector.op("@@")(tsquery))
        .order_by(rank.desc())
        .limit(limit)
    )
    if group_id:
        stmt = stmt.where(Note.group_id == group_id)

    result = await db.execute(stmt)
    return [
        {
            "note_id": str(note.id),
            "title": note.title,
            "type": note.type,
            "group_id": str(note.group_id) if note.group_id else None,
            "snippet": snippet_text,
            "score": score,
        }
        for note, score, snippet_text in result.all()
    ]


async def search_semantic(
    db: AsyncSession, project_id: uuid.UUID, query: str, group_id: uuid.UUID | None, embedding_model: str, limit: int = 20
) -> list[dict]:
    vectors = await embed_texts([query], embedding_model)
    query_vector = vectors[0]
    distance_expr = EmbeddingChunk.embedding.cosine_distance(query_vector)
    similarity_expr = 1 - distance_expr

    stmt = (
        select(EmbeddingChunk, Note, similarity_expr.label("similarity"))
        .join(Note, EmbeddingChunk.note_id == Note.id)
        .where(Note.project_id == project_id)
        .order_by(distance_expr)
        .limit(SEMANTIC_OVERFETCH)
    )
    if group_id:
        stmt = stmt.where(Note.group_id == group_id)

    result = await db.execute(stmt)

    best_by_note: dict[uuid.UUID, dict] = {}
    for chunk, note, similarity in result.all():
        existing = best_by_note.get(note.id)
        if existing and existing["score"] >= similarity:
            continue
        best_by_note[note.id] = {
            "note_id": str(note.id),
            "title": note.title,
            "type": note.type,
            "group_id": str(note.group_id) if note.group_id else None,
            "snippet": chunk.content[:280],
            "score": similarity,
        }

    return sorted(best_by_note.values(), key=lambda r: r["score"], reverse=True)[:limit]
