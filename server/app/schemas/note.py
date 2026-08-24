import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class NoteCreate(BaseModel):
    project_id: uuid.UUID
    group_id: uuid.UUID | None = None
    type: Literal["text", "audio", "video", "document"]
    title: str
    body: str | None = None


class NoteUpdate(BaseModel):
    group_id: uuid.UUID | None = None
    title: str | None = None
    body: str | None = None


class NoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    group_id: uuid.UUID | None
    type: str
    title: str
    body: str | None
    summary: str | None
    status: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime
