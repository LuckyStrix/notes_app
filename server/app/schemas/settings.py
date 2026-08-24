from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class SettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    app_name: str | None
    llm_provider: Literal["ollama", "anthropic"]
    ollama_chat_model: str
    anthropic_chat_model: str
    has_anthropic_api_key: bool
    embedding_model: str
    whisper_model: str
    whisper_idle_unload_seconds: int
    updated_at: datetime


class SettingsUpdate(BaseModel):
    app_name: str | None = None
    llm_provider: Literal["ollama", "anthropic"] | None = None
    ollama_chat_model: str | None = None
    anthropic_chat_model: str | None = None
    anthropic_api_key: str | None = None
    embedding_model: str | None = None
    whisper_model: str | None = None
    whisper_idle_unload_seconds: int | None = None
