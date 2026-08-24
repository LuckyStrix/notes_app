from collections.abc import AsyncIterator

from ollama import AsyncClient
from pydantic import ValidationError

from app.config import settings
from app.llm.base import LLMProvider, Message, SchemaT


class OllamaProvider(LLMProvider):
    def __init__(self, model: str):
        self._model = model
        self._client = AsyncClient(host=settings.ollama_base_url)

    def model_name(self) -> str:
        return self._model

    async def chat(self, messages: list[Message], *, system: str | None = None) -> AsyncIterator[str]:
        ollama_messages = []
        if system:
            ollama_messages.append({"role": "system", "content": system})
        ollama_messages.extend({"role": m.role, "content": m.content} for m in messages)

        stream = await self._client.chat(model=self._model, messages=ollama_messages, stream=True)
        async for chunk in stream:
            content = chunk.get("message", {}).get("content", "")
            if content:
                yield content

    async def structured_extract(self, prompt: str, schema: type[SchemaT]) -> SchemaT:
        # Passing the JSON schema itself as `format` (rather than the literal
        # "json") makes Ollama constrain decoding via grammar, so the output
        # shape is enforced structurally instead of merely prompted for --
        # small local models are unreliable at just following a schema
        # described in text (they'll happily echo the schema back verbatim).
        schema_json = schema.model_json_schema()

        last_error: str | None = None
        for attempt in range(2):
            instructions = prompt if attempt == 0 else f"{prompt}\n\n(Previous attempt was invalid: {last_error})"
            response = await self._client.chat(
                model=self._model,
                messages=[{"role": "user", "content": instructions}],
                format=schema_json,
                stream=False,
            )
            raw = response["message"]["content"]
            try:
                return schema.model_validate_json(raw)
            except ValidationError as exc:
                last_error = str(exc)

        raise ValueError(f"Ollama structured_extract failed validation after retries: {last_error}")
