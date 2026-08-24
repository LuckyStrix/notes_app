from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class Project(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    groups: Mapped[list["Group"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    notes: Mapped[list["Note"]] = relationship(back_populates="project", cascade="all, delete-orphan")
