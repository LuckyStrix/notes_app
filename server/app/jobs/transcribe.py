import asyncio
import os
import uuid

from sqlalchemy import select

from app.config import settings
from app.db import async_session
from app.models.media import NoteFile, Transcript, TranscriptSegment
from app.models.note import Note
from app.models.settings import AppSettings
from app.queue import DEFAULT_RETRY, job_queue
from app.services.search import update_note_search_vector


def transcribe_note(note_id: str) -> None:
    """RQ entrypoint. RQ's default Worker forks a fresh child process per job,
    so loading the whisper model here (inside the child, after fork) is safe --
    CUDA is never initialized in the long-lived parent listener process. The
    upside: GPU memory is fully released the moment this job's process exits,
    so an idle-unload timer isn't needed -- the worker never holds VRAM
    between jobs at all.
    """
    asyncio.run(_transcribe_note(note_id))


async def _transcribe_note(note_id: str) -> None:
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

        app_settings = await db.get(AppSettings, 1)
        whisper_model_name = app_settings.whisper_model if app_settings else "small"

        note.status = "processing"
        await db.commit()

        file_path = os.path.join(settings.upload_dir, note_file.storage_path)

        try:
            full_text, language, duration, segments = await asyncio.to_thread(
                _run_whisper, file_path, whisper_model_name
            )
        except Exception as exc:  # noqa: BLE001 -- surface any transcription failure on the note itself
            note.status = "error"
            note.error_message = f"Transcription failed: {exc}"
            await db.commit()
            return

        transcript = Transcript(
            note_id=note.id,
            full_text=full_text,
            language=language,
            whisper_model=whisper_model_name,
        )
        db.add(transcript)
        await db.flush()

        for idx, seg in enumerate(segments):
            db.add(
                TranscriptSegment(
                    transcript_id=transcript.id,
                    segment_index=idx,
                    start_time=seg["start"],
                    end_time=seg["end"],
                    text=seg["text"],
                    words=seg["words"],
                )
            )

        note_file.duration_seconds = duration
        note.status = "ready"
        await update_note_search_vector(db, note, extra_text=full_text)
        await db.commit()

    job_queue.enqueue("app.jobs.embed.embed_note", note_id, job_timeout=600, retry=DEFAULT_RETRY)
    job_queue.enqueue(
        "app.jobs.extract_keywords.extract_keywords", note_id, job_timeout=600, retry=DEFAULT_RETRY
    )


def _run_whisper(file_path: str, model_name: str):
    """Blocking faster-whisper call -- runs in a worker thread via asyncio.to_thread."""
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="cuda", compute_type="float16")
    segments_iter, info = model.transcribe(file_path, word_timestamps=True, vad_filter=True)

    segments = []
    full_text_parts = []
    for seg in segments_iter:
        words = (
            [{"word": w.word, "start": w.start, "end": w.end, "confidence": w.probability} for w in seg.words]
            if seg.words
            else None
        )
        text = seg.text.strip()
        segments.append({"start": seg.start, "end": seg.end, "text": text, "words": words})
        full_text_parts.append(text)

    return " ".join(full_text_parts), info.language, info.duration, segments
