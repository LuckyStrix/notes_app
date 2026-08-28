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
    # Set by boundary-event saves (blur, navigate-away, tab-close) to force a
    # NoteVersion snapshot regardless of the usual ~60s throttle -- see
    # app.api.notes.update_note. Left False on the routine debounced autosave.
    force_version: bool = False


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


class NoteVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    body: str | None
    created_at: datetime
