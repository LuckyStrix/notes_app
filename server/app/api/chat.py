import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.llm.base import Message
from app.llm.factory import get_active_provider
from app.models.chat import ChatMessage, ChatSession, Citation
from app.models.note import Note
from app.models.settings import AppSettings
from app.schemas.chat import ChatMessageCreate, ChatMessageRead, ChatSessionCreate, ChatSessionRead
from app.services.rag import (
    SUMMARIZE_RESET_PROMPT,
    build_citations_payload,
    build_context_block,
    build_system_prompt,
    generate_llm_text,
    retrieve_chunks,
)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/sessions", response_model=ChatSessionRead, status_code=201)
async def create_session(payload: ChatSessionCreate, db: AsyncSession = Depends(get_db)):
    session = ChatSession(project_id=payload.project_id, title=payload.title)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/sessions", response_model=list[ChatSessionRead])
async def list_sessions(project_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db)):
    stmt = select(ChatSession).order_by(ChatSession.created_at.desc())
    if project_id:
        stmt = stmt.where(ChatSession.project_id == project_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageRead])
async def list_messages(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .options(selectinload(ChatMessage.citations))
        .order_by(ChatMessage.created_at)
    )
    messages = result.scalars().all()

    note_ids = {c.note_id for m in messages for c in m.citations}
    titles: dict[uuid.UUID, str] = {}
    if note_ids:
        note_result = await db.execute(select(Note.id, Note.title).where(Note.id.in_(note_ids)))
        titles = dict(note_result.all())

    output = []
    for m in messages:
        read = ChatMessageRead.model_validate(m)
        for citation in read.citations:
            citation.note_title = titles.get(citation.note_id)
        output.append(read)
    return output


@router.post("/sessions/{session_id}/summarize-reset", response_model=ChatSessionRead, status_code=201)
async def summarize_reset(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    session = await db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    history_result = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at)
    )
    history = history_result.scalars().all()
    if not history:
        raise HTTPException(status_code=400, detail="Nothing to summarize yet")

    transcript = "\n\n".join(f"{m.role}: {m.content}" for m in history)
    provider = await get_active_provider(db)
    summary_text = await generate_llm_text(
        provider, [Message(role="user", content=transcript)], system=SUMMARIZE_RESET_PROMPT
    )

    new_session = ChatSession(project_id=session.project_id, title=session.title)
    db.add(new_session)
    await db.flush()
    db.add(
        ChatMessage(
            session_id=new_session.id, role="assistant", content=f"[Conversation summary]\n\n{summary_text}"
        )
    )
    await db.commit()
    await db.refresh(new_session)
    return new_session


@router.post("/sessions/{session_id}/messages")
async def post_message(session_id: uuid.UUID, payload: ChatMessageCreate, db: AsyncSession = Depends(get_db)):
    session = await db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    app_settings = await db.get(AppSettings, 1)
    embedding_model = app_settings.embedding_model if app_settings else "nomic-embed-text"

    db.add(ChatMessage(session_id=session_id, role="user", content=payload.content))
    await db.commit()

    rows = await retrieve_chunks(
        db,
        payload.content,
        project_id=session.project_id,
        group_id=payload.group_id,
        embedding_model=embedding_model,
    )
    system_prompt = build_system_prompt(build_context_block(rows))

    history_result = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at)
    )
    conversation = [Message(role=m.role, content=m.content) for m in history_result.scalars().all()]

    provider = await get_active_provider(db)

    async def event_stream():
        parts: list[str] = []
        try:
            async for chunk in provider.chat(conversation, system=system_prompt):
                parts.append(chunk)
                yield f"event: token\ndata: {json.dumps(chunk)}\n\n"
        except Exception as exc:  # noqa: BLE001 -- surface provider errors to the client stream
            yield f"event: error\ndata: {json.dumps(str(exc))}\n\n"
            return

        full_text = "".join(parts)
        assistant_message = ChatMessage(session_id=session_id, role="assistant", content=full_text)
        db.add(assistant_message)
        await db.flush()

        citations_payload = build_citations_payload(full_text, rows)
        for citation in citations_payload:
            db.add(
                Citation(
                    message_id=assistant_message.id,
                    note_id=uuid.UUID(citation["note_id"]),
                    chunk_id=uuid.UUID(citation["chunk_id"]),
                    start_time=citation["start_time"],
                    end_time=citation["end_time"],
                    page_start=citation["page_start"],
                    page_end=citation["page_end"],
                    confidence=citation["confidence"],
                    quote=citation["quote"],
                    ordinal=citation["ordinal"],
                )
            )
        await db.commit()

        yield f"event: citations\ndata: {json.dumps(citations_payload)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
