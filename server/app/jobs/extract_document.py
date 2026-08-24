import asyncio
import os
import uuid

from sqlalchemy import select

from app.config import settings
from app.db import async_session
from app.models.media import NoteFile
from app.models.note import Note
from app.queue import DEFAULT_RETRY, job_queue
from app.services.search import update_note_search_vector

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


def extract_document_text(note_id: str) -> None:
    asyncio.run(_extract_document_text(note_id))


async def _extract_document_text(note_id: str) -> None:
    async with async_session() as db:
        note = await db.get(Note, uuid.UUID(note_id))
        if note is None:
            return

        result = await db.execute(select(NoteFile).where(NoteFile.note_id == note.id))
        note_file = result.scalar_one_or_none()
        if note_file is None:
            note.status = "error"
            note.error_message = "No uploaded file found for this note"
            await db.commit()
            return

        note.status = "processing"
        await db.commit()

        file_path = os.path.join(settings.upload_dir, note_file.storage_path)

        try:
            text = await asyncio.to_thread(_extract_text, file_path, note_file.original_filename or "")
        except Exception as exc:  # noqa: BLE001 -- surface any extraction failure on the note itself
            note.status = "error"
            note.error_message = f"Text extraction failed: {exc}"
            await db.commit()
            return

        if not text.strip():
            note.status = "error"
            note.error_message = (
                "No extractable text was found in this file -- it may be a scanned/image-only "
                "document with no text layer."
            )
            await db.commit()
            return

        note.body = text
        note.status = "ready"
        await update_note_search_vector(db, note)
        await db.commit()

    job_queue.enqueue("app.jobs.embed.embed_note", note_id, job_timeout=600, retry=DEFAULT_RETRY)
    job_queue.enqueue("app.jobs.extract_keywords.extract_keywords", note_id, job_timeout=600, retry=DEFAULT_RETRY)


def _extract_text(file_path: str, original_filename: str) -> str:
    """Blocking extraction -- runs in a worker thread via asyncio.to_thread."""
    ext = os.path.splitext(original_filename.lower())[1] or os.path.splitext(file_path.lower())[1]

    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported document type: {ext or 'unknown'}")
    if ext == ".pdf":
        return _extract_pdf(file_path)
    if ext == ".docx":
        return _extract_docx(file_path)
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _extract_pdf(file_path: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(file_path)
    pages = []
    for i, page in enumerate(reader.pages):
        page_text = (page.extract_text() or "").strip()
        pages.append(f"--- Page {i + 1} ---\n{page_text}")
    return "\n\n".join(pages)


def _extract_docx(file_path: str) -> str:
    import docx

    document = docx.Document(file_path)
    return "\n\n".join(p.text for p in document.paragraphs if p.text.strip())
