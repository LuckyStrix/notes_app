import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.llm.factory import get_active_provider
from app.models.keyword import Keyword, KeywordEdge, NoteKeyword
from app.models.note import Note
from app.models.project import Project
from app.models.settings import AppSettings
from app.queue import DEFAULT_RETRY, job_queue
from app.services.rag import build_summary_system_prompt, run_grounded_summary

router = APIRouter(tags=["graph"])


@router.post("/projects/{project_id}/graph/rebuild", status_code=202)
async def rebuild_graph(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    # Set eagerly (rather than waiting for the worker to pick up the job) so
    # the client's very first poll after this call already sees "processing",
    # not a stale "ready" from before the rebuild was requested.
    project.graph_status = "processing"
    project.graph_error = None
    await db.commit()
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


async def _get_project_edge(db: AsyncSession, project_id: uuid.UUID, source_id: uuid.UUID, target_id: uuid.UUID) -> KeywordEdge:
    # Stored source/target ordering comes from rebuild_graph's cooccurrence
    # merge, not from whichever direction the client's graph click supplies,
    # so both orderings have to be checked here.
    stmt = select(KeywordEdge).where(
        KeywordEdge.project_id == project_id,
        (
            ((KeywordEdge.source_keyword_id == source_id) & (KeywordEdge.target_keyword_id == target_id))
            | ((KeywordEdge.source_keyword_id == target_id) & (KeywordEdge.target_keyword_id == source_id))
        ),
    )
    edge = (await db.execute(stmt)).scalar_one_or_none()
    if not edge:
        raise HTTPException(status_code=404, detail="Edge not found")
    return edge


def _summary_response(title: str, row: Keyword | KeywordEdge) -> dict:
    """Prefers the quality tier when both are present -- it's the more
    thorough one, so it's what should show up front if a node has both."""
    tier = "quality" if row.quality_summary else ("basic" if row.basic_summary else None)
    content = row.quality_summary if row.quality_summary else row.basic_summary
    citations = (row.quality_summary_citations if row.quality_summary else row.basic_summary_citations) or []
    generated_at = row.quality_summary_generated_at if row.quality_summary else row.basic_summary_generated_at
    return {
        "title": title,
        "content": content,
        "citations": citations,
        "tier": tier,
        "generated_at": generated_at.isoformat() if generated_at else None,
    }


@router.get("/projects/{project_id}/graph/keywords/{keyword_id}/summary")
async def get_keyword_summary(project_id: uuid.UUID, keyword_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    keyword = await _get_project_keyword(db, project_id, keyword_id)
    return _summary_response(keyword.label, keyword)


@router.post("/projects/{project_id}/graph/keywords/{keyword_id}/summary/quality")
async def generate_keyword_quality_summary(
    project_id: uuid.UUID, keyword_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    keyword = await _get_project_keyword(db, project_id, keyword_id)
    prompt = (
        f'Summarize the topic "{keyword.label}" based on the notes below. If the notes don\'t say much '
        "about it, briefly explain what this topic generally means instead."
    )
    app_settings = await db.get(AppSettings, 1)
    project = await db.get(Project, project_id)
    provider = await get_active_provider(db)
    result = await run_grounded_summary(
        db,
        provider,
        project_id=project_id,
        project=project,
        app_settings=app_settings,
        query=keyword.label,
        prompt=prompt,
        system_prompt_builder=build_summary_system_prompt,
    )
    keyword.quality_summary = result["content"]
    keyword.quality_summary_citations = result["citations"]
    keyword.quality_summary_generated_at = datetime.now(timezone.utc)
    await db.commit()
    return _summary_response(keyword.label, keyword)


@router.get("/projects/{project_id}/graph/edges/summary")
async def get_edge_summary(
    project_id: uuid.UUID, source: uuid.UUID, target: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    source_kw = await _get_project_keyword(db, project_id, source)
    target_kw = await _get_project_keyword(db, project_id, target)
    edge = await _get_project_edge(db, project_id, source, target)
    return _summary_response(f"{source_kw.label} <-> {target_kw.label}", edge)


@router.post("/projects/{project_id}/graph/edges/summary/quality")
async def generate_edge_quality_summary(
    project_id: uuid.UUID, source: uuid.UUID, target: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    source_kw = await _get_project_keyword(db, project_id, source)
    target_kw = await _get_project_keyword(db, project_id, target)
    edge = await _get_project_edge(db, project_id, source, target)
    query = f"the relationship between {source_kw.label} and {target_kw.label}"
    prompt = (
        f'Explain how "{source_kw.label}" and "{target_kw.label}" are connected, based on the notes below. '
        "If it's not obvious from the notes, explain how these topics are generally related instead."
    )
    app_settings = await db.get(AppSettings, 1)
    project = await db.get(Project, project_id)
    provider = await get_active_provider(db)
    result = await run_grounded_summary(
        db,
        provider,
        project_id=project_id,
        project=project,
        app_settings=app_settings,
        query=query,
        prompt=prompt,
        system_prompt_builder=build_summary_system_prompt,
    )
    edge.quality_summary = result["content"]
    edge.quality_summary_citations = result["citations"]
    edge.quality_summary_generated_at = datetime.now(timezone.utc)
    await db.commit()
    return _summary_response(f"{source_kw.label} <-> {target_kw.label}", edge)


@router.post("/projects/{project_id}/graph/summaries/generate-all", status_code=202)
async def generate_all_summaries(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    app_settings = await db.get(AppSettings, 1)
    if not app_settings or not app_settings.ollama_fast_model:
        raise HTTPException(status_code=400, detail="No fast Ollama model is configured (set one in Settings first)")

    keyword_count = (
        await db.execute(select(func.count()).select_from(Keyword).where(Keyword.project_id == project_id))
    ).scalar_one()
    edge_count = (
        await db.execute(select(func.count()).select_from(KeywordEdge).where(KeywordEdge.project_id == project_id))
    ).scalar_one()
    total = keyword_count + edge_count

    project.summary_generation_status = "processing"
    project.summary_generation_error = None
    project.summary_generation_progress = 0
    project.summary_generation_total = total
    await db.commit()

    job_queue.enqueue(
        "app.jobs.generate_graph_summaries.generate_all_summaries",
        str(project_id),
        job_timeout=max(600, 20 * total),
        retry=DEFAULT_RETRY,
    )
    return {"status": "queued", "total": total}
