import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.db import async_session
from app.llm.factory import get_fast_ollama_provider
from app.models.keyword import Keyword, KeywordEdge
from app.models.project import Project
from app.models.settings import AppSettings
from app.services.rag import build_basic_summary_system_prompt, run_grounded_summary


def generate_all_summaries(project_id: str) -> None:
    asyncio.run(_generate_all_summaries(project_id))


async def _mark_status(project_id: uuid.UUID, status: str, error: str | None = None) -> None:
    async with async_session() as db:
        project = await db.get(Project, project_id)
        if not project:
            return
        project.summary_generation_status = status
        project.summary_generation_error = error
        await db.commit()


async def _generate_all_summaries(project_id: str) -> None:
    pid = uuid.UUID(project_id)

    try:
        async with async_session() as db:
            app_settings = await db.get(AppSettings, 1)
            project = await db.get(Project, pid)
            if not project or not app_settings or not app_settings.ollama_fast_model:
                await _mark_status(pid, "error", "No fast Ollama model is configured")
                return
            provider = await get_fast_ollama_provider(db)

            keywords = (await db.execute(select(Keyword).where(Keyword.project_id == pid))).scalars().all()
            edges = (await db.execute(select(KeywordEdge).where(KeywordEdge.project_id == pid))).scalars().all()
            keywords_by_id = {k.id: k for k in keywords}

            progress = 0
            for keyword in keywords:
                prompt = (
                    f'Summarize the topic "{keyword.label}" based on the notes below. If the notes don\'t say much '
                    "about it, say so briefly instead of guessing."
                )
                result = await run_grounded_summary(
                    db,
                    provider,
                    project_id=pid,
                    project=project,
                    app_settings=app_settings,
                    query=keyword.label,
                    prompt=prompt,
                    system_prompt_builder=build_basic_summary_system_prompt,
                )
                keyword.basic_summary = result["content"]
                keyword.basic_summary_citations = result["citations"]
                keyword.basic_summary_generated_at = datetime.now(timezone.utc)
                progress += 1
                project.summary_generation_progress = progress
                await db.commit()

            for edge in edges:
                source_kw = keywords_by_id.get(edge.source_keyword_id)
                target_kw = keywords_by_id.get(edge.target_keyword_id)
                if not source_kw or not target_kw:
                    progress += 1
                    project.summary_generation_progress = progress
                    await db.commit()
                    continue
                query = f"the relationship between {source_kw.label} and {target_kw.label}"
                prompt = (
                    f'Explain how "{source_kw.label}" and "{target_kw.label}" are connected, based on the notes '
                    "below. If it's not obvious from the notes, say so briefly instead of guessing."
                )
                result = await run_grounded_summary(
                    db,
                    provider,
                    project_id=pid,
                    project=project,
                    app_settings=app_settings,
                    query=query,
                    prompt=prompt,
                    system_prompt_builder=build_basic_summary_system_prompt,
                )
                edge.basic_summary = result["content"]
                edge.basic_summary_citations = result["citations"]
                edge.basic_summary_generated_at = datetime.now(timezone.utc)
                progress += 1
                project.summary_generation_progress = progress
                await db.commit()
    except Exception as exc:
        await _mark_status(pid, "error", str(exc))
        raise
    else:
        await _mark_status(pid, "ready")
