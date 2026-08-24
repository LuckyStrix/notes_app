import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.settings import AppSettings
from app.services.search import search_literal, search_semantic

router = APIRouter(tags=["search"])


@router.get("/projects/{project_id}/search")
async def search(
    project_id: uuid.UUID,
    q: str,
    mode: Literal["literal", "semantic"] = "literal",
    group_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    if mode == "literal":
        return await search_literal(db, project_id, q, group_id)

    app_settings = await db.get(AppSettings, 1)
    embedding_model = app_settings.embedding_model if app_settings else "nomic-embed-text"
    return await search_semantic(db, project_id, q, group_id, embedding_model)
