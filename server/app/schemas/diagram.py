import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DiagramCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    note_id: uuid.UUID
    source_page: int | None
    source_timestamp: float | None
    ordinal: int


class DiagramSaveRequest(BaseModel):
    candidate_ids: list[uuid.UUID]


class DiagramRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    note_id: uuid.UUID
    source_page: int | None
    source_timestamp: float | None
    ocr_text: str | None
    caption: str | None
    status: str
    error_message: str | None
    created_at: datetime
