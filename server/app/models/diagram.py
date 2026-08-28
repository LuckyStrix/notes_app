import uuid

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class DiagramCandidate(UUIDPKMixin, TimestampMixin, Base):
    """An ephemeral, unreviewed image pulled out of a note's source file (a
    rendered/embedded PDF page image, or a video keyframe) -- shown to the
    user to pick from. Regenerated (old rows + files deleted) each time
    "Find diagrams" is run; only the ones the user picks become a Diagram.
    """

    __tablename__ = "diagram_candidates"

    note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False
    )
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_timestamp: Mapped[float | None] = mapped_column(Float)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


class Diagram(UUIDPKMixin, TimestampMixin, Base):
    """A user-selected diagram/keyframe, permanently kept and OCR'd/captioned
    (app.jobs.process_diagrams) so it's searchable and citable in chat like
    any other note content."""

    __tablename__ = "diagrams"
    __table_args__ = (CheckConstraint("status IN ('processing','ready','error')", name="ck_diagrams_status"),)

    note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False
    )
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_timestamp: Mapped[float | None] = mapped_column(Float)
    ocr_text: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="processing")
    error_message: Mapped[str | None] = mapped_column(Text)
