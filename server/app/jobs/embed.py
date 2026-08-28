import asyncio
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.db import async_session
from app.llm.embeddings import embed_texts
from app.models.embedding import EmbeddingChunk
from app.models.media import Transcript
from app.models.note import Note
from app.models.settings import AppSettings
from app.services.chunking import PAGE_MARKER_RE, chunk_document_pages, chunk_segments, chunk_text


def embed_note(note_id: str) -> None:
    asyncio.run(_embed_note(note_id))


async def _embed_note(note_id: str) -> None:
    async with async_session() as db:
        note = await db.get(Note, uuid.UUID(note_id))
        if note is None:
            return

        app_settings = await db.get(AppSettings, 1)
        embedding_model = app_settings.embedding_model if app_settings else "nomic-embed-text"

        chunk_rows: list[dict] = []
        if note.type in ("text", "document") and note.body:
            if note.type == "document" and PAGE_MARKER_RE.search(note.body):
                page_chunks = chunk_document_pages(note.body)
            else:
                page_chunks = [{"text": t, "page_start": None, "page_end": None} for t in chunk_text(note.body)]
            for idx, c in enumerate(page_chunks):
                chunk_rows.append(
                    {
                        "source": "note_body",
                        "chunk_index": idx,
                        "content": c["text"],
                        "start_time": None,
                        "end_time": None,
                        "segment_id_start": None,
                        "segment_id_end": None,
                        "page_start": c["page_start"],
                        "page_end": c["page_end"],
                    }
                )
        elif note.type in ("audio", "video"):
            result = await db.execute(
                select(Transcript).where(Transcript.note_id == note.id).options(selectinload(Transcript.segments))
            )
            transcript = result.scalar_one_or_none()
            if transcript and transcript.segments:
                for idx, c in enumerate(chunk_segments(transcript.segments)):
                    chunk_rows.append(
                        {
                            "source": "transcript",
                            "chunk_index": idx,
                            "content": c["text"],
                            "start_time": c["start_time"],
                            "end_time": c["end_time"],
                            "segment_id_start": c["segment_id_start"],
                            "segment_id_end": c["segment_id_end"],
                            "page_start": None,
                            "page_end": None,
                        }
                    )

        # Replace any existing note_body/transcript chunks for this note --
        # keeps re-embedding on edit/re-transcribe idempotent rather than
        # accumulating stale rows. Diagram chunks are untouched here; they're
        # only ever replaced by app.jobs.process_diagrams, which owns them.
        await db.execute(
            delete(EmbeddingChunk).where(EmbeddingChunk.note_id == note.id, EmbeddingChunk.source != "diagram")
        )
        await db.flush()

        if not chunk_rows:
            await db.commit()
            return

        vectors = await embed_texts([c["content"] for c in chunk_rows], embedding_model)

        for chunk, vector in zip(chunk_rows, vectors):
            db.add(EmbeddingChunk(note_id=note.id, embedding=vector, embedding_model=embedding_model, **chunk))

        await db.commit()
