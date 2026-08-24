import asyncio
import uuid

from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.db import async_session
from app.llm.embeddings import embed_texts
from app.llm.factory import get_active_provider
from app.models.keyword import Keyword, NoteKeyword
from app.models.media import Transcript
from app.models.note import Note
from app.models.settings import AppSettings
from app.queue import DEFAULT_RETRY, job_queue


class KeywordExtractionResult(BaseModel):
    keywords: list[str] = Field(description="5-15 salient keywords, technical terms, or named entities")


def extract_keywords(note_id: str) -> None:
    asyncio.run(_extract_keywords(note_id))


async def _extract_keywords(note_id: str) -> None:
    project_id: uuid.UUID | None = None

    async with async_session() as db:
        note = await db.get(Note, uuid.UUID(note_id))
        if note is None:
            return
        project_id = note.project_id

        text = note.body
        if note.type in ("audio", "video"):
            result = await db.execute(select(Transcript.full_text).where(Transcript.note_id == note.id))
            text = result.scalar_one_or_none()

        if not text or not text.strip():
            return

        app_settings = await db.get(AppSettings, 1)
        embedding_model = app_settings.embedding_model if app_settings else "nomic-embed-text"

        provider = await get_active_provider(db)
        prompt = (
            "Extract the 5-15 most salient keywords, technical terms, or named entities from the "
            "text below. Use short, concise canonical forms (e.g. 'Raft consensus' not 'the Raft "
            "consensus algorithm we discussed').\n\nText:\n" + text[:6000]
        )
        try:
            extraction = await provider.structured_extract(prompt, KeywordExtractionResult)
        except Exception:
            # Keyword graph is a supplementary feature, not critical path -- a
            # flaky local-model extraction shouldn't fail the whole note.
            return

        terms = [t.strip() for t in extraction.keywords if t.strip()]
        if not terms:
            return

        old_kw_result = await db.execute(select(NoteKeyword.keyword_id).where(NoteKeyword.note_id == note.id))
        old_keyword_ids = set(old_kw_result.scalars().all())

        # Re-extraction on edit is idempotent: drop this note's prior associations first.
        await db.execute(delete(NoteKeyword).where(NoteKeyword.note_id == note.id))
        await db.flush()

        normalized_to_term: dict[str, str] = {}
        for term in terms:
            normalized_to_term.setdefault(term.lower().strip(), term)

        existing_result = await db.execute(
            select(Keyword).where(
                Keyword.project_id == note.project_id,
                Keyword.normalized_label.in_(list(normalized_to_term.keys())),
            )
        )
        existing = {k.normalized_label: k for k in existing_result.scalars().all()}

        missing = [n for n in normalized_to_term if n not in existing]
        if missing:
            missing_labels = [normalized_to_term[n] for n in missing]
            vectors = await embed_texts(missing_labels, embedding_model)
            for normalized, label, vector in zip(missing, missing_labels, vectors):
                kw = Keyword(project_id=note.project_id, label=label, normalized_label=normalized, embedding=vector)
                db.add(kw)
                existing[normalized] = kw
            await db.flush()

        for normalized in normalized_to_term:
            db.add(NoteKeyword(note_id=note.id, keyword_id=existing[normalized].id, relevance=1.0))

        new_keyword_ids = {existing[normalized].id for normalized in normalized_to_term}
        await db.commit()

    if project_id:
        job_queue.enqueue(
            "app.jobs.rebuild_graph.rebuild_project_graph_incremental",
            str(project_id),
            str(note.id),
            [str(k) for k in old_keyword_ids],
            [str(k) for k in new_keyword_ids],
            job_timeout=600,
            retry=DEFAULT_RETRY,
        )
