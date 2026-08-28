import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import UUIDPKMixin
from app.models.embedding import EMBEDDING_DIM


class Keyword(UUIDPKMixin, Base):
    __tablename__ = "keywords"
    __table_args__ = (UniqueConstraint("project_id", "normalized_label"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_label: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    significance: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")

    # Persisted graph-summary tiers (server.app.api.graph) -- basic comes from
    # the fast/notes-only "Generate All" batch job, quality from the existing
    # RAG-grounded pipeline triggered per-node. NULL means "not generated yet".
    basic_summary: Mapped[str | None] = mapped_column(Text)
    basic_summary_citations: Mapped[list | None] = mapped_column(JSON)
    basic_summary_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quality_summary: Mapped[str | None] = mapped_column(Text)
    quality_summary_citations: Mapped[list | None] = mapped_column(JSON)
    quality_summary_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NoteKeyword(Base):
    __tablename__ = "note_keywords"

    note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True
    )
    keyword_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("keywords.id", ondelete="CASCADE"), primary_key=True
    )
    relevance: Mapped[float | None] = mapped_column(Float)


class KeywordEdge(UUIDPKMixin, Base):
    __tablename__ = "keyword_edges"
    __table_args__ = (UniqueConstraint("project_id", "source_keyword_id", "target_keyword_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_keyword_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("keywords.id", ondelete="CASCADE"), nullable=False
    )
    target_keyword_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("keywords.id", ondelete="CASCADE"), nullable=False
    )
    cooccurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    embedding_similarity: Mapped[float | None] = mapped_column(Float)
    significance: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")

    basic_summary: Mapped[str | None] = mapped_column(Text)
    basic_summary_citations: Mapped[list | None] = mapped_column(JSON)
    basic_summary_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quality_summary: Mapped[str | None] = mapped_column(Text)
    quality_summary_citations: Mapped[list | None] = mapped_column(JSON)
    quality_summary_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
