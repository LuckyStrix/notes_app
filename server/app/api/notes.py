import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.note import Note
from app.models.note_version import NoteVersion
from app.queue import DEFAULT_RETRY, job_queue
from app.schemas.note import NoteCreate, NoteRead, NoteUpdate, NoteVersionRead
from app.services.search import update_note_search_vector
from app.services.storage import delete_note_storage

router = APIRouter(prefix="/notes", tags=["notes"])

# Throttle for routine (non-boundary) autosave snapshots -- see
# _maybe_snapshot_version below.
VERSION_SNAPSHOT_INTERVAL = timedelta(seconds=60)


async def _maybe_snapshot_version(db: AsyncSession, note: Note, force: bool) -> None:
    """Snapshots the note's *current* (already-applied) title/body as a
    NoteVersion if `force` is set (a boundary-event save: blur, navigate-away,
    tab-close) or if enough time has passed since the last snapshot -- so
    routine 800ms-debounced autosaves don't create a version per keystroke
    pause, while every real save boundary is still guaranteed a recovery
    point."""
    if not force:
        last = (
            await db.execute(
                select(NoteVersion.created_at)
                .where(NoteVersion.note_id == note.id)
                .order_by(NoteVersion.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if last is not None and datetime.now(timezone.utc) - last < VERSION_SNAPSHOT_INTERVAL:
            return
    db.add(NoteVersion(note_id=note.id, title=note.title, body=note.body))
    await db.commit()


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
    fields = payload.model_dump(exclude_unset=True, exclude={"force_version"})
    for field, value in fields.items():
        setattr(note, field, value)
    await db.commit()
    await db.refresh(note)

    if "title" in fields or "body" in fields:
        await update_note_search_vector(db, note)
        await db.commit()
        await db.refresh(note)
        await _maybe_snapshot_version(db, note, force=payload.force_version)

    if note.type == "text" and "body" in fields:
        job_queue.enqueue("app.jobs.embed.embed_note", str(note.id), job_timeout=600, retry=DEFAULT_RETRY)
        job_queue.enqueue(
            "app.jobs.extract_keywords.extract_keywords", str(note.id), job_timeout=600, retry=DEFAULT_RETRY
        )

    return note


@router.post("/{note_id}/autosave-beacon", status_code=204)
async def autosave_beacon(note_id: uuid.UUID, payload: NoteUpdate, db: AsyncSession = Depends(get_db)):
    """Same partial-update logic as PATCH, exposed as a POST so the client
    can call it via navigator.sendBeacon on tab-close/hide -- sendBeacon only
    supports POST and its response is never read, hence the plain 204 here
    rather than reusing update_note's response model."""
    note = await db.get(Note, note_id)
    if not note:
        return
    fields = payload.model_dump(exclude_unset=True, exclude={"force_version"})
    for field, value in fields.items():
        setattr(note, field, value)
    await db.commit()
    await db.refresh(note)

    if "title" in fields or "body" in fields:
        await update_note_search_vector(db, note)
        await db.commit()
        await db.refresh(note)
        await _maybe_snapshot_version(db, note, force=True)

    if note.type == "text" and "body" in fields:
        job_queue.enqueue("app.jobs.embed.embed_note", str(note.id), job_timeout=600, retry=DEFAULT_RETRY)
        job_queue.enqueue(
            "app.jobs.extract_keywords.extract_keywords", str(note.id), job_timeout=600, retry=DEFAULT_RETRY
        )


@router.get("/{note_id}/versions", response_model=list[NoteVersionRead])
async def list_note_versions(note_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(NoteVersion).where(NoteVersion.note_id == note_id).order_by(NoteVersion.created_at.desc()).limit(50)
    )
    return result.scalars().all()


@router.post("/{note_id}/versions/{version_id}/restore", response_model=NoteRead)
async def restore_note_version(note_id: uuid.UUID, version_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    note = await db.get(Note, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    version = await db.get(NoteVersion, version_id)
    if not version or version.note_id != note_id:
        raise HTTPException(status_code=404, detail="Version not found")

    # Snapshot the pre-restore state first so restoring is itself undoable.
    db.add(NoteVersion(note_id=note.id, title=note.title, body=note.body))

    note.title = version.title
    note.body = version.body
    await db.commit()
    await db.refresh(note)

    await update_note_search_vector(db, note)
    await db.commit()
    await db.refresh(note)

    if note.type == "text":
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
