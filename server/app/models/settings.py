from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column


from app.db import Base


class AppSettings(Base):
    __tablename__ = "app_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_app_settings_singleton"),
        CheckConstraint("llm_provider IN ('ollama','anthropic')", name="ck_app_settings_provider"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    app_name: Mapped[str | None] = mapped_column(String(255))
    llm_provider: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ollama")
    ollama_chat_model: Mapped[str] = mapped_column(
        String(128), nullable=False, server_default="qwen2.5:14b-instruct-q4_K_M"
    )
    anthropic_chat_model: Mapped[str] = mapped_column(
        String(128), nullable=False, server_default="claude-sonnet-4-5"
    )
    anthropic_api_key: Mapped[str | None] = mapped_column(String(255))
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False, server_default="nomic-embed-text")
    whisper_model: Mapped[str] = mapped_column(String(32), nullable=False, server_default="small")
    whisper_idle_unload_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="300")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
