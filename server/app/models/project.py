from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class Project(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("rag_top_k IS NULL OR rag_top_k > 0", name="ck_projects_rag_top_k"),
        CheckConstraint(
            "rag_similarity_floor IS NULL OR (rag_similarity_floor >= 0 AND rag_similarity_floor <= 1)",
            name="ck_projects_rag_similarity_floor",
        ),
        CheckConstraint("graph_status IN ('ready','processing','error')", name="ck_projects_graph_status"),
        CheckConstraint(
            "summary_generation_status IN ('idle','processing','ready','error')",
            name="ck_projects_summary_generation_status",
        ),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # Per-project overrides for chat retrieval (server.app.services.rag) --
    # NULL means "inherit AppSettings.default_rag_top_k / default_rag_similarity_floor".
    # Useful because how much context a question needs scales with how big/
    # noisy a project's notes are, not with anything global.
    rag_top_k: Mapped[int | None] = mapped_column(Integer)
    rag_similarity_floor: Mapped[float | None] = mapped_column(Float)
    # Display order on the home page -- lower sorts first. Backfilled by
    # creation order when this column was introduced; reassigned wholesale by
    # the drag-and-drop reorder endpoint from then on.
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Tracks the async keyword-graph rebuild job (app.jobs.rebuild_graph),
    # mirroring Note.status, so the client can poll for completion instead of
    # guessing how long a rebuild takes.
    graph_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ready")
    graph_error: Mapped[str | None] = mapped_column(Text)
    graph_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Tracks the async "Generate All" basic-summary batch job
    # (app.jobs.generate_graph_summaries), same polling shape as graph_status.
    summary_generation_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="idle")
    summary_generation_error: Mapped[str | None] = mapped_column(Text)
    summary_generation_progress: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    summary_generation_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    groups: Mapped[list["Group"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    notes: Mapped[list["Note"]] = relationship(back_populates="project", cascade="all, delete-orphan")
