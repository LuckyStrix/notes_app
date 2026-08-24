import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ChatSessionCreate(BaseModel):
    project_id: uuid.UUID | None = None
    title: str | None = None


class ChatSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID | None
    title: str | None
    created_at: datetime


class ChatMessageCreate(BaseModel):
    content: str
    group_id: uuid.UUID | None = None


class CitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ordinal: int
    note_id: uuid.UUID
    note_title: str | None = None
    chunk_id: uuid.UUID | None
    start_time: float | None
    end_time: float | None
    page_start: int | None = None
    page_end: int | None = None
    confidence: str | None = None
    quote: str | None


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    created_at: datetime
    citations: list[CitationRead]
