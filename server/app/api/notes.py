import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.note import Note
from app.queue import DEFAULT_RETRY, job_queue
from app.schemas.note import NoteCreate, NoteRead, NoteUpdate
from app.services.search import update_note_search_vector
from app.services.storage import delete_note_storage

router = APIRouter(prefix="/notes", tags=["notes"])


@router.get("", response_model=list[NoteRead])
async def list_notes(
    project_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Note).order_by(Note.created_at.desc())
    if project_id:
        stmt = stmt.where(Note.project_id == project_id)
    if group_id:
        stmt = stmt.where(Note.group_id == group_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=NoteRead, status_code=201)
async def create_note(payload: NoteCreate, db: AsyncSession = Depends(get_db)):
    # Text notes are ready immediately; audio/video notes start "pending" until
    # a file is uploaded via /media and picked up by the transcription worker.
    status = "ready" if payload.type == "text" else "pending"
    note = Note(**payload.model_dump(), status=status)
    db.add(note)
    await db.commit()
    await db.refresh(note)

    await update_note_search_vector(db, note)
    await db.commit()
    await db.refresh(note)

    if note.type == "text" and note.body:
        job_queue.enqueue("app.jobs.embed.embed_note", str(note.id), job_timeout=600, retry=DEFAULT_RETRY)
        job_queue.enqueue(
            "app.jobs.extract_keywords.extract_keywords", str(note.id), job_timeout=600, retry=DEFAULT_RETRY
        )

    return note


@router.get("/{note_id}", response_model=NoteRead)
async def get_note(note_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    note = await db.get(Note, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.patch("/{note_id}", response_model=NoteRead)
async def update_note(note_id: uuid.UUID, payload: NoteUpdate, db: AsyncSession = Depends(get_db)):
    note = await db.get(Note, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    fields = payload.model_dump(exclude_unset=True)
    for field, value in fields.items():
        setattr(note, field, value)
    await db.commit()
    await db.refresh(note)

    if "title" in fields or "body" in fields:
        await update_note_search_vector(db, note)
        await db.commit()
        await db.refresh(note)

    if note.type == "text" and "body" in fields:
        job_queue.enqueue("app.jobs.embed.embed_note", str(note.id), job_timeout=600, retry=DEFAULT_RETRY)
        job_queue.enqueue(
            "app.jobs.extract_keywords.extract_keywords", str(note.id), job_timeout=600, retry=DEFAULT_RETRY
        )

    return note


@router.delete("/{note_id}", status_code=204)
async def delete_note(note_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    note = await db.get(Note, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    await db.delete(note)
    await db.commit()
    delete_note_storage(note_id)
