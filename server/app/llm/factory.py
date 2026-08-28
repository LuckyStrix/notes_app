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
        num_ctx = row.num_ctx if row else 8192
        return OllamaProvider(model, num_ctx)

    api_key = row.anthropic_api_key or app_config.anthropic_api_key
    if not api_key:
        raise ValueError(
            "Anthropic provider is selected but no API key is configured "
            "(set it in Settings or via the ANTHROPIC_API_KEY env var)"
        )
    return AnthropicProvider(row.anthropic_chat_model, api_key)


async def get_fast_ollama_provider(db: AsyncSession) -> OllamaProvider:
    """Always Ollama, regardless of AppSettings.llm_provider -- used only by
    the keyword graph's "Generate All" batch job (app.jobs.generate_graph_summaries),
    which explicitly wants a small/fast local model over whatever the app's
    main chat provider is (which could be Anthropic). Raises if no fast model
    is configured rather than silently falling back to the main chat model,
    since that would defeat the point of a separate fast tier.
    """
    row = await db.get(AppSettings, 1)
    if row is None or not row.ollama_fast_model:
        raise ValueError("No fast Ollama model is configured (set one in Settings first)")
    num_ctx = row.num_ctx if row else 8192
    return OllamaProvider(row.ollama_fast_model, num_ctx)
