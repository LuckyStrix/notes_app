import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NoteFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    note_id: uuid.UUID
    original_filename: str | None
    mime_type: str | None
    duration_seconds: float | None
    size_bytes: int | None
    candidate_status: str | None
    candidate_error: str | None
    candidates_generated_at: datetime | None


class TranscriptSegmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    segment_index: int
    start_time: float
    end_time: float
    text: str
    words: list | None


class TranscriptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    note_id: uuid.UUID
    full_text: str | None
    language: str | None
    whisper_model: str | None
    segments: list[TranscriptSegmentRead]
