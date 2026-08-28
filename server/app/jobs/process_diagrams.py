import asyncio
import uuid
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.db import async_session
from app.llm.embeddings import embed_texts
from app.llm.vision import caption_image
from app.models.diagram import Diagram
from app.models.embedding import EmbeddingChunk
from app.models.settings import AppSettings


def process_saved_diagrams(note_id: str, diagram_ids: list[str]) -> None:
    asyncio.run(_process_saved_diagrams(note_id, diagram_ids))


def _run_ocr(path: Path) -> str:
    import pytesseract
    from PIL import Image

    with Image.open(path) as img:
        return pytesseract.image_to_string(img).strip()


async def _process_saved_diagrams(note_id: str, diagram_ids: list[str]) -> None:
    nid = uuid.UUID(note_id)
    ids = [uuid.UUID(d) for d in diagram_ids]

    async with async_session() as db:
        app_settings = await db.get(AppSettings, 1)
        embedding_model = app_settings.embedding_model if app_settings else "nomic-embed-text"
        vision_model = app_settings.ollama_vision_model if app_settings else None

        result = await db.execute(select(Diagram).where(Diagram.id.in_(ids)))
        diagrams = result.scalars().all()

        # (diagram, content) pairs ready to embed -- built up as each
        # diagram's OCR/captioning succeeds, so one bad image doesn't stop
        # the rest of the batch from being processed.
        to_embed: list[tuple[Diagram, str]] = []
        for diagram in diagrams:
            path = Path(settings.upload_dir) / diagram.storage_path
            try:
                ocr_text = await asyncio.to_thread(_run_ocr, path)
                caption = None
                if vision_model:
                    try:
                        caption = await caption_image(str(path), vision_model)
                    except Exception:
                        # OCR text alone still makes the diagram searchable;
                        # a captioning failure (model not pulled, OOM, etc.)
                        # shouldn't fail the whole save.
                        caption = None
                diagram.ocr_text = ocr_text
                diagram.caption = caption
                diagram.status = "ready"
                content = "\n\n".join(p for p in (caption, ocr_text) if p and p.strip())
                if content:
                    to_embed.append((diagram, content))
            except Exception as exc:
                diagram.status = "error"
                diagram.error_message = str(exc)
        await db.commit()

        if not to_embed:
            return

        vectors = await embed_texts([content for _, content in to_embed], embedding_model)
        for (diagram, content), vector in zip(to_embed, vectors):
            db.add(
                EmbeddingChunk(
                    note_id=nid,
                    source="diagram",
                    chunk_index=0,
                    content=content,
                    start_time=diagram.source_timestamp,
                    end_time=diagram.source_timestamp,
                    page_start=diagram.source_page,
                    page_end=diagram.source_page,
                    diagram_id=diagram.id,
                    embedding=vector,
                    embedding_model=embedding_model,
                )
            )
        await db.commit()
