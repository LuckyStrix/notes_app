import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.note import Note
from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services.storage import delete_note_storage

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectReorder(BaseModel):
    project_ids: list[uuid.UUID]


@router.get("", response_model=list[ProjectRead])
async def list_projects(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).order_by(Project.position))
    return result.scalars().all()


@router.post("", response_model=ProjectRead, status_code=201)
async def create_project(payload: ProjectCreate, db: AsyncSession = Depends(get_db)):
    # New projects sort last, below every existing one.
    max_position = (await db.execute(select(func.max(Project.position)))).scalar()
    project = Project(**payload.model_dump(), position=(max_position + 1) if max_position is not None else 0)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


# Registered before /{project_id} so this literal path isn't shadowed by the
# path-parameter route below.
@router.patch("/reorder", response_model=list[ProjectRead])
async def reorder_projects(payload: ProjectReorder, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id.in_(payload.project_ids)))
    projects_by_id = {p.id: p for p in result.scalars().all()}
    for index, project_id in enumerate(payload.project_ids):
        if project_id in projects_by_id:
            projects_by_id[project_id].position = index
    await db.commit()

    result = await db.execute(select(Project).order_by(Project.position))
    return result.scalars().all()


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(project_id: uuid.UUID, payload: ProjectUpdate, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    note_ids = (await db.execute(select(Note.id).where(Note.project_id == project_id))).scalars().all()
    await db.delete(project)
    await db.commit()
    for note_id in note_ids:
        delete_note_storage(note_id)
