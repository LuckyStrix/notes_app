import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.llm.base import Message
from app.llm.factory import get_active_provider
from app.models.keyword import Keyword, KeywordEdge, NoteKeyword
from app.models.note import Note
from app.models.settings import AppSettings
from app.queue import DEFAULT_RETRY, job_queue
from app.services.rag import build_citations_payload, build_context_block, build_summary_system_prompt, generate_llm_text, retrieve_chunks

router = APIRouter(tags=["graph"])


@router.post("/projects/{project_id}/graph/rebuild", status_code=202)
async def rebuild_graph(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    job_queue.enqueue(
        "app.jobs.rebuild_graph.rebuild_project_graph", str(project_id), job_timeout=600, retry=DEFAULT_RETRY
    )
    return {"status": "queued"}


@router.get("/projects/{project_id}/graph")
async def get_graph(
    project_id: uuid.UUID,
    significance: float = 0.0,
    group_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    node_stmt = select(Keyword).where(Keyword.project_id == project_id, Keyword.significance >= significance)
    if group_id:
        note_ids_subq = select(Note.id).where(Note.group_id == group_id)
        keyword_ids_subq = select(NoteKeyword.keyword_id).where(NoteKeyword.note_id.in_(note_ids_subq))
        node_stmt = node_stmt.where(Keyword.id.in_(keyword_ids_subq))

    nodes = (await db.execute(node_stmt)).scalars().all()
    node_ids = {n.id for n in nodes}

    note_counts: dict[uuid.UUID, int] = {}
    if node_ids:
        count_stmt = (
            select(NoteKeyword.keyword_id, func.count(NoteKeyword.note_id))
            .where(NoteKeyword.keyword_id.in_(node_ids))
            .group_by(NoteKeyword.keyword_id)
        )
        note_counts = dict((await db.execute(count_stmt)).all())

    edges = []
    if node_ids:
        edge_stmt = select(KeywordEdge).where(
            KeywordEdge.project_id == project_id,
            KeywordEdge.significance >= significance,
            KeywordEdge.source_keyword_id.in_(node_ids),
            KeywordEdge.target_keyword_id.in_(node_ids),
        )
        edges = (await db.execute(edge_stmt)).scalars().all()

    return {
        "nodes": [
            {
                "id": str(n.id),
                "label": n.label,
                "significance": n.significance,
                "note_count": note_counts.get(n.id, 0),
            }
            for n in nodes
        ],
        "edges": [
            {
                "source": str(e.source_keyword_id),
                "target": str(e.target_keyword_id),
                "significance": e.significance,
                "cooccurrence_count": e.cooccurrence_count,
            }
            for e in edges
        ],
    }


async def _get_project_keyword(db: AsyncSession, project_id: uuid.UUID, keyword_id: uuid.UUID) -> Keyword:
    keyword = await db.get(Keyword, keyword_id)
    if not keyword or keyword.project_id != project_id:
        raise HTTPException(status_code=404, detail="Keyword not found")
    return keyword


async def _run_summary(db: AsyncSession, project_id: uuid.UUID, query: str, prompt: str) -> dict:
    app_settings = await db.get(AppSettings, 1)
    embedding_model = app_settings.embedding_model if app_settings else "nomic-embed-text"

    rows = await retrieve_chunks(db, query, project_id=project_id, group_id=None, embedding_model=embedding_model)
    system_prompt = build_summary_system_prompt(build_context_block(rows))

    provider = await get_active_provider(db)
    full_text = await generate_llm_text(provider, [Message(role="user", content=prompt)], system=system_prompt)

    return {"content": full_text, "citations": build_citations_payload(full_text, rows)}


@router.get("/projects/{project_id}/graph/keywords/{keyword_id}/summary")
async def get_keyword_summary(project_id: uuid.UUID, keyword_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    keyword = await _get_project_keyword(db, project_id, keyword_id)
    prompt = (
        f'Summarize the topic "{keyword.label}" based on the notes below. If the notes don\'t say much '
        "about it, briefly explain what this topic generally means instead."
    )
    result = await _run_summary(db, project_id, keyword.label, prompt)
    return {"title": keyword.label, **result}


@router.get("/projects/{project_id}/graph/edges/summary")
async def get_edge_summary(
    project_id: uuid.UUID, source: uuid.UUID, target: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    source_kw = await _get_project_keyword(db, project_id, source)
    target_kw = await _get_project_keyword(db, project_id, target)
    query = f"the relationship between {source_kw.label} and {target_kw.label}"
    prompt = (
        f'Explain how "{source_kw.label}" and "{target_kw.label}" are connected, based on the notes below. '
        "If it's not obvious from the notes, explain how these topics are generally related instead."
    )
    result = await _run_summary(db, project_id, query, prompt)
    return {"title": f"{source_kw.label} <-> {target_kw.label}", **result}
