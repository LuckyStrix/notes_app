import asyncio
import os
import uuid
from pathlib import Path

import cv2
import fitz  # PyMuPDF
from sqlalchemy import delete, func, select

from app.config import settings
from app.db import async_session
from app.models.diagram import DiagramCandidate
from app.models.media import NoteFile
from app.models.note import Note

MAX_PDF_PAGES = 60
MIN_EMBEDDED_IMAGE_DIM = 100  # px; skip tiny icons/bullets, not real diagrams
MAX_VIDEO_CANDIDATES = 40
VIDEO_SAMPLE_INTERVAL_SECONDS = 1.0
# Scene-change threshold on a 0-1 normalized mean grayscale pixel difference
# between consecutive *sampled* frames -- a starting point, not a tuned
# value. Talking-head video and slide-deck screen recordings behave very
# differently; revisit if candidates come back too noisy or too sparse, the
# same way rag.py's similarity-floor constants are treated.
SCENE_CHANGE_THRESHOLD = 0.08


def generate_diagram_candidates(note_id: str) -> None:
    asyncio.run(_generate_diagram_candidates(note_id))


async def _mark_candidate_status(note_id: uuid.UUID, status: str, error: str | None = None) -> None:
    async with async_session() as db:
        result = await db.execute(select(NoteFile).where(NoteFile.note_id == note_id))
        note_file = result.scalar_one_or_none()
        if not note_file:
            return
        note_file.candidate_status = status
        note_file.candidate_error = error
        if status == "ready":
            note_file.candidates_generated_at = func.now()
        await db.commit()


def _delete_file_quiet(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


async def _generate_diagram_candidates(note_id: str) -> None:
    nid = uuid.UUID(note_id)
    await _mark_candidate_status(nid, "processing")

    try:
        async with async_session() as db:
            note = await db.get(Note, nid)
            result = await db.execute(select(NoteFile).where(NoteFile.note_id == nid))
            note_file = result.scalar_one_or_none()
            if not note or not note_file:
                raise ValueError("No uploaded file found for this note")

            # Regenerate replaces, rather than accumulating, prior candidates.
            old_candidates = (
                await db.execute(select(DiagramCandidate).where(DiagramCandidate.note_id == nid))
            ).scalars().all()
            for c in old_candidates:
                _delete_file_quiet(Path(settings.upload_dir) / c.storage_path)
            await db.execute(delete(DiagramCandidate).where(DiagramCandidate.note_id == nid))
            await db.flush()

            file_path = os.path.join(settings.upload_dir, note_file.storage_path)
            candidates_dir = Path(settings.upload_dir) / note_id / "diagram_candidates"
            candidates_dir.mkdir(parents=True, exist_ok=True)

            is_pdf = (note_file.original_filename or "").lower().endswith(".pdf")
            if note.type == "document" and is_pdf:
                specs = await asyncio.to_thread(_extract_pdf_candidates, file_path, candidates_dir)
            elif note.type == "video":
                specs = await asyncio.to_thread(_extract_video_candidates, file_path, candidates_dir)
            else:
                # Non-PDF documents (docx/txt) and audio: no candidates, not an error.
                specs = []

            for ordinal, spec in enumerate(specs):
                db.add(
                    DiagramCandidate(
                        note_id=nid,
                        storage_path=str(spec["path"].relative_to(settings.upload_dir)),
                        source_page=spec.get("source_page"),
                        source_timestamp=spec.get("source_timestamp"),
                        ordinal=ordinal,
                    )
                )
            await db.commit()
    except Exception as exc:
        await _mark_candidate_status(nid, "error", str(exc))
        return
    await _mark_candidate_status(nid, "ready")


def _extract_pdf_candidates(file_path: str, out_dir: Path) -> list[dict]:
    specs = []
    doc = fitz.open(file_path)
    try:
        page_count = min(doc.page_count, MAX_PDF_PAGES)
        for page_index in range(page_count):
            page = doc[page_index]
            page_num = page_index + 1

            # Full-page render, so a diagram drawn with vector shapes (not a
            # discrete embedded raster image) is still capturable.
            pix = page.get_pixmap(dpi=150)
            page_path = out_dir / f"page-{page_num}.png"
            pix.save(str(page_path))
            specs.append({"path": page_path, "source_page": page_num})

            # Embedded raster images too, separately -- lets the user pick
            # just the diagram out of a busy page instead of the whole page.
            for img_index, img in enumerate(page.get_images(full=True)):
                xref = img[0]
                base_image = doc.extract_image(xref)
                width, height = base_image.get("width", 0), base_image.get("height", 0)
                if width < MIN_EMBEDDED_IMAGE_DIM or height < MIN_EMBEDDED_IMAGE_DIM:
                    continue
                ext = base_image.get("ext", "png")
                img_path = out_dir / f"page-{page_num}-img-{img_index}.{ext}"
                img_path.write_bytes(base_image["image"])
                specs.append({"path": img_path, "source_page": page_num})
    finally:
        doc.close()
    return specs


def _extract_video_candidates(file_path: str, out_dir: Path) -> list[dict]:
    cap = cv2.VideoCapture(file_path)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_interval = max(1, int(fps * VIDEO_SAMPLE_INTERVAL_SECONDS))

        scored = []  # (diff_score, timestamp, frame)
        first_frame = None
        prev_gray = None
        frame_index = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_index % frame_interval == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                timestamp = frame_index / fps
                if first_frame is None:
                    first_frame = (timestamp, frame)
                elif prev_gray is not None:
                    diff = cv2.absdiff(gray, prev_gray).mean() / 255.0
                    if diff >= SCENE_CHANGE_THRESHOLD:
                        scored.append((diff, timestamp, frame))
                prev_gray = gray
            frame_index += 1
    finally:
        cap.release()

    # Always keep the very first sampled frame, then the highest-scoring
    # scene changes up to the cap, restored to chronological order.
    scored.sort(key=lambda s: s[0], reverse=True)
    kept = scored[: MAX_VIDEO_CANDIDATES - 1]
    kept.sort(key=lambda s: s[1])

    specs = []
    if first_frame is not None:
        ts, frame = first_frame
        path = out_dir / f"t-{ts:.2f}.jpg"
        cv2.imwrite(str(path), frame)
        specs.append({"path": path, "source_timestamp": ts})
    for _, ts, frame in kept:
        path = out_dir / f"t-{ts:.2f}.jpg"
        cv2.imwrite(str(path), frame)
        specs.append({"path": path, "source_timestamp": ts})
    return specs
