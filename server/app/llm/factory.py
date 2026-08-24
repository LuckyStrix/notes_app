from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_config
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import LLMProvider
from app.llm.ollama_provider import OllamaProvider
from app.models.settings import AppSettings

DEFAULT_OLLAMA_MODEL = "qwen2.5:14b-instruct-q4_K_M"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"


async def get_active_provider(db: AsyncSession) -> LLMProvider:
    """Reads app_settings fresh on every call so a provider/model switch in
    Settings takes effect on the very next request -- no restart needed.
    """
    row = await db.get(AppSettings, 1)

    if row is None or row.llm_provider == "ollama":
        model = row.ollama_chat_model if row else DEFAULT_OLLAMA_MODEL
        return OllamaProvider(model)

    api_key = row.anthropic_api_key or app_config.anthropic_api_key
    if not api_key:
        raise ValueError(
            "Anthropic provider is selected but no API key is configured "
            "(set it in Settings or via the ANTHROPIC_API_KEY env var)"
        )
    return AnthropicProvider(row.anthropic_chat_model, api_key)
