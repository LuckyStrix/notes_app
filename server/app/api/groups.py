import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.group import Group
from app.schemas.group import GroupCreate, GroupRead, GroupUpdate

router = APIRouter(tags=["groups"])


@router.get("/projects/{project_id}/groups", response_model=list[GroupRead])
async def list_groups(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Group).where(Group.project_id == project_id).order_by(Group.created_at))
    return result.scalars().all()


@router.post("/projects/{project_id}/groups", response_model=GroupRead, status_code=201)
async def create_group(project_id: uuid.UUID, payload: GroupCreate, db: AsyncSession = Depends(get_db)):
    group = Group(project_id=project_id, **payload.model_dump())
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return group


@router.patch("/groups/{group_id}", response_model=GroupRead)
async def update_group(group_id: uuid.UUID, payload: GroupUpdate, db: AsyncSession = Depends(get_db)):
    group = await db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    await db.commit()
    await db.refresh(group)
    return group


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(group_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    group = await db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    await db.delete(group)
    await db.commit()
