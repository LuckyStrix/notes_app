import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.diagram import Diagram, DiagramCandidate
from app.models.media import NoteFile
from app.models.note import Note
from app.queue import DEFAULT_RETRY, job_queue
from app.schemas.diagram import DiagramCandidateRead, DiagramRead, DiagramSaveRequest
from app.services.storage import resolve_within

router = APIRouter(prefix="/notes/{note_id}/diagrams", tags=["diagrams"])


@router.post("/generate-candidates", status_code=202)
async def generate_candidates(note_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    note = await db.get(Note, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    result = await db.execute(select(NoteFile).where(NoteFile.note_id == note_id))
    note_file = result.scalar_one_or_none()
    if not note_file:
        raise HTTPException(status_code=400, detail="No uploaded file for this note yet")

    # Set eagerly so the client's first poll already sees "processing".
    note_file.candidate_status = "processing"
    note_file.candidate_error = None
    await db.commit()

    job_queue.enqueue(
        "app.jobs.extract_diagrams.generate_diagram_candidates", str(note_id), job_timeout=900, retry=DEFAULT_RETRY
    )
    return {"status": "queued"}


@router.get("/candidates", response_model=list[DiagramCandidateRead])
async def list_candidates(note_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DiagramCandidate).where(DiagramCandidate.note_id == note_id).order_by(DiagramCandidate.ordinal)
    )
    return result.scalars().all()


@router.get("/candidates/{candidate_id}/file")
async def get_candidate_file(note_id: uuid.UUID, candidate_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    candidate = await db.get(DiagramCandidate, candidate_id)
    if not candidate or candidate.note_id != note_id:
        raise HTTPException(status_code=404, detail="Candidate not found")
    try:
        path = resolve_within(Path(settings.upload_dir), candidate.storage_path)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid stored file path")
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(path)


@router.post("", response_model=list[DiagramRead], status_code=201)
async def save_diagrams(note_id: uuid.UUID, payload: DiagramSaveRequest, db: AsyncSession = Depends(get_db)):
    note = await db.get(Note, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    result = await db.execute(
        select(DiagramCandidate).where(
            DiagramCandidate.id.in_(payload.candidate_ids), DiagramCandidate.note_id == note_id
        )
    )
    candidates = result.scalars().all()
    if not candidates:
        raise HTTPException(status_code=400, detail="No matching candidates found")

    diagrams_dir = Path(settings.upload_dir) / str(note_id) / "diagrams"
    diagrams_dir.mkdir(parents=True, exist_ok=True)

    created: list[Diagram] = []
    for candidate in candidates:
        src = resolve_within(Path(settings.upload_dir), candidate.storage_path)
        diagram = Diagram(
            note_id=note_id,
            storage_path="",  # filled in below once we know the new id
            source_page=candidate.source_page,
            source_timestamp=candidate.source_timestamp,
            status="processing",
        )
        db.add(diagram)
        await db.flush()  # assigns diagram.id

        dest = diagrams_dir / f"{diagram.id}{src.suffix}"
        shutil.copyfile(src, dest)
        diagram.storage_path = str(dest.relative_to(settings.upload_dir))
        created.append(diagram)

    await db.commit()
    for diagram in created:
        await db.refresh(diagram)

    job_queue.enqueue(
        "app.jobs.process_diagrams.process_saved_diagrams",
        str(note_id),
        [str(d.id) for d in created],
        job_timeout=600,
        retry=DEFAULT_RETRY,
    )
    return created


@router.get("", response_model=list[DiagramRead])
async def list_diagrams(note_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Diagram).where(Diagram.note_id == note_id).order_by(Diagram.created_at))
    return result.scalars().all()


@router.get("/{diagram_id}/file")
async def get_diagram_file(note_id: uuid.UUID, diagram_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    diagram = await db.get(Diagram, diagram_id)
    if not diagram or diagram.note_id != note_id:
        raise HTTPException(status_code=404, detail="Diagram not found")
    try:
        path = resolve_within(Path(settings.upload_dir), diagram.storage_path)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid stored file path")
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(path)


@router.delete("/{diagram_id}", status_code=204)
async def delete_diagram(note_id: uuid.UUID, diagram_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    diagram = await db.get(Diagram, diagram_id)
    if not diagram or diagram.note_id != note_id:
        raise HTTPException(status_code=404, detail="Diagram not found")
    try:
        path = resolve_within(Path(settings.upload_dir), diagram.storage_path)
        path.unlink(missing_ok=True)
    except ValueError:
        pass
    await db.delete(diagram)
    await db.commit()
