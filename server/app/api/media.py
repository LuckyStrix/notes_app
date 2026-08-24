import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import get_db
from app.models.media import NoteFile, Transcript
from app.models.note import Note
from app.queue import DEFAULT_RETRY, job_queue
from app.schemas.media import NoteFileRead, TranscriptRead

router = APIRouter(tags=["media"])


@router.post("/notes/{note_id}/media", response_model=NoteFileRead, status_code=201)
async def upload_media(note_id: uuid.UUID, file: UploadFile, db: AsyncSession = Depends(get_db)):
    note = await db.get(Note, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if note.type not in ("audio", "video", "document"):
        raise HTTPException(status_code=400, detail="This note type doesn't accept a file upload")

    # Re-uploading replaces the previous file/transcript for this note (1:1 relationship).
    existing = await db.execute(select(NoteFile).where(NoteFile.note_id == note_id))
    if existing_file := existing.scalar_one_or_none():
        await db.delete(existing_file)
    existing_transcript = await db.execute(select(Transcript).where(Transcript.note_id == note_id))
    if existing_transcript_row := existing_transcript.scalar_one_or_none():
        await db.delete(existing_transcript_row)
    await db.flush()

    note_dir = Path(settings.upload_dir) / str(note_id)
    note_dir.mkdir(parents=True, exist_ok=True)
    dest_path = note_dir / (file.filename or "upload")

    size = 0
    with dest_path.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            out.write(chunk)
            size += len(chunk)

    note_file = NoteFile(
        note_id=note_id,
        storage_path=str(dest_path.relative_to(settings.upload_dir)),
        original_filename=file.filename,
        mime_type=file.content_type,
        size_bytes=size,
    )
    db.add(note_file)
    note.status = "pending"
    await db.commit()
    await db.refresh(note_file)

    if note.type in ("audio", "video"):
        job_queue.enqueue(
            "app.jobs.transcribe.transcribe_note", str(note_id), job_timeout=3600, retry=DEFAULT_RETRY
        )
    else:  # document
        job_queue.enqueue(
            "app.jobs.extract_document.extract_document_text", str(note_id), job_timeout=300, retry=DEFAULT_RETRY
        )

    return note_file


@router.get("/notes/{note_id}/media", response_model=NoteFileRead)
async def get_media_info(note_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NoteFile).where(NoteFile.note_id == note_id))
    note_file = result.scalar_one_or_none()
    if not note_file:
        raise HTTPException(status_code=404, detail="No file for this note")
    return note_file


@router.get("/notes/{note_id}/media/file")
async def get_media_file(note_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NoteFile).where(NoteFile.note_id == note_id))
    note_file = result.scalar_one_or_none()
    if not note_file:
        raise HTTPException(status_code=404, detail="No file for this note")
    path = Path(settings.upload_dir) / note_file.storage_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(path, media_type=note_file.mime_type or "application/octet-stream")


@router.get("/notes/{note_id}/transcript", response_model=TranscriptRead)
async def get_transcript(note_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Transcript).where(Transcript.note_id == note_id).options(selectinload(Transcript.segments))
    )
    transcript = result.scalar_one_or_none()
    if not transcript:
        raise HTTPException(status_code=404, detail="No transcript yet")
    return transcript
