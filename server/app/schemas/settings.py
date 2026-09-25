from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.transcription import LANGUAGE_PATTERN


class SettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    app_name: str | None
    llm_provider: Literal["ollama", "anthropic"]
    ollama_chat_model: str
    ollama_fast_model: str | None
    anthropic_chat_model: str
    has_anthropic_api_key: bool
    embedding_model: str
    ollama_vision_model: str | None
    whisper_model: str
    whisper_language: str
    whisper_idle_unload_seconds: int
    default_rag_top_k: int
    default_rag_similarity_floor: float
    num_ctx: int
    backup_enabled: bool
    backup_frequency: Literal["daily", "weekly"]
    backup_keep: int
    updated_at: datetime


class SettingsUpdate(BaseModel):
    app_name: str | None = None
    llm_provider: Literal["ollama", "anthropic"] | None = None
    ollama_chat_model: str | None = None
    ollama_fast_model: str | None = None
    anthropic_chat_model: str | None = None
    anthropic_api_key: str | None = None
    embedding_model: str | None = None
    ollama_vision_model: str | None = None
    whisper_model: str | None = None
    whisper_language: str | None = Field(default=None, pattern=LANGUAGE_PATTERN)
    whisper_idle_unload_seconds: int | None = None
    default_rag_top_k: int | None = Field(default=None, ge=1, le=50)
    default_rag_similarity_floor: float | None = Field(default=None, ge=0, le=1)
    num_ctx: int | None = Field(default=None, ge=1)
    backup_enabled: bool | None = None
    backup_frequency: Literal["daily", "weekly"] | None = None
    backup_keep: int | None = Field(default=None, ge=1, le=60)
