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
from app.services.transcription import resolve_language


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
        whisper_language = app_settings.whisper_language if app_settings else "en"

        note.status = "processing"
        await db.commit()

        file_path = os.path.join(settings.upload_dir, note_file.storage_path)

        try:
            full_text, language, duration, segments = await asyncio.to_thread(
                _run_whisper, file_path, whisper_model_name, whisper_language
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


def _run_whisper(file_path: str, model_name: str, language: str = "en"):
    """Blocking faster-whisper call -- runs in a worker thread via asyncio.to_thread.

    `language` is passed explicitly (see services.transcription): left to
    auto-detect, Whisper guesses from the first 30 seconds and labelled English
    lectures as Welsh, then transcribed them as Welsh-looking gibberish. "auto"
    (Settings) opts back in to auto-detection.

    vad_filter is deliberately off. It sounds like the right tool for "quiet
    recording produces no transcript," but measured against a real quiet
    lecture recording that came back with zero segments, Silero VAD (the
    filter faster-whisper applies) was the actual cause -- it discarded most
    of the genuine speech throughout the file as "not speech," at every
    onset threshold tried (default 0.5 down to 0.2). With vad_filter off,
    the same file transcribed correctly end to end. Loudness normalization
    (ffmpeg loudnorm, plain gain boost) was tried first and didn't reliably
    help -- it left VAD's rejections almost unchanged, and a naive gain
    boost made things worse by clipping the recording's louder moments.
    condition_on_previous_text is also off: on long recordings it can lock
    onto a bad transcription and repeat it, and disabling it is the standard
    mitigation. Whisper's own per-window no_speech/compression-ratio/logprob
    heuristics (on by default, independent of VAD) still suppress hallucinated
    text during genuine silence -- confirmed against this file's own silent
    stretches before making this the default for every note, not just this one.
    """
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="cuda", compute_type="float16")
    segments_iter, info = model.transcribe(
        file_path,
        language=resolve_language(language),
        word_timestamps=True,
        vad_filter=False,
        condition_on_previous_text=False,
    )

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
