from ollama import AsyncClient

from app.config import settings

# Embeddings are always local regardless of the active chat provider -- Anthropic
# has no embeddings API, so this doesn't participate in the ollama/anthropic switch.


async def embed_texts(texts: list[str], model: str) -> list[list[float]]:
    if not texts:
        return []
    client = AsyncClient(host=settings.ollama_base_url)
    result = await client.embed(model=model, input=texts)
    return result["embeddings"]
