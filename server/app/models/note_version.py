import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import UUIDPKMixin


class NoteVersion(UUIDPKMixin, Base):
    """An immutable snapshot of a note's title/body, taken at throttled
    intervals during editing (see app.api.notes.update_note) -- a safety net
    against accidental data loss, not a full editor history."""

    __tablename__ = "note_versions"
    __table_args__ = (Index("ix_note_versions_note_id_created_at", "note_id", "created_at"),)

    note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
