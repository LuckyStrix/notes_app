import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Float, String, Text, UniqueConstraint, BigInteger
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class NoteFile(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "note_files"

    note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(512))
    mime_type: Mapped[str | None] = mapped_column(String(128))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    # Tracks app.jobs.extract_diagrams.generate_diagram_candidates, mirroring
    # Note.status -- null means "never run for this file".
    candidate_status: Mapped[str | None] = mapped_column(String(20))
    candidate_error: Mapped[str | None] = mapped_column(Text)
    candidates_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Transcript(UUIDPKMixin, Base):
    __tablename__ = "transcripts"

    note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    full_text: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(16))
    whisper_model: Mapped[str | None] = mapped_column(String(32))

    segments: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="transcript", cascade="all, delete-orphan", order_by="TranscriptSegment.segment_index"
    )


class TranscriptSegment(UUIDPKMixin, Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (UniqueConstraint("transcript_id", "segment_index"),)

    transcript_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False
    )
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    words: Mapped[list | None] = mapped_column(JSONB)

    transcript: Mapped["Transcript"] = relationship(back_populates="segments")
