import base64

from ollama import AsyncClient

from app.config import settings

CAPTION_PROMPT = (
    "Describe this image concisely, focusing on any diagram, chart, or on-screen text structure. "
    "If it's a slide or document page, summarize what it's illustrating rather than just listing what's on it."
)


async def caption_image(image_path: str, model: str) -> str:
    """A plain function rather than an LLMProvider method -- captioning
    always goes through a local Ollama vision model regardless of which
    provider is active for chat (see AppSettings.ollama_vision_model), so it
    doesn't belong on the shared provider-swap interface."""
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()

    client = AsyncClient(host=settings.ollama_base_url)
    response = await client.chat(
        model=model,
        messages=[{"role": "user", "content": CAPTION_PROMPT, "images": [image_b64]}],
        stream=False,
    )
    return response["message"]["content"]
