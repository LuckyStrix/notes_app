from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic

from app.llm.base import LLMProvider, Message, SchemaT

MAX_TOKENS = 4096


class AnthropicProvider(LLMProvider):
    def __init__(self, model: str, api_key: str):
        self._model = model
        self._client = AsyncAnthropic(api_key=api_key)

    def model_name(self) -> str:
        return self._model

    async def chat(self, messages: list[Message], *, system: str | None = None) -> AsyncIterator[str]:
        anthropic_messages = [{"role": m.role, "content": m.content} for m in messages]
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=MAX_TOKENS,
            system=system or "",
            messages=anthropic_messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text

    async def structured_extract(self, prompt: str, schema: type[SchemaT]) -> SchemaT:
        tool_name = "extract"
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
            tools=[
                {
                    "name": tool_name,
                    "description": "Extract structured data matching the given schema.",
                    "input_schema": schema.model_json_schema(),
                }
            ],
            tool_choice={"type": "tool", "name": tool_name},
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == tool_name:
                return schema.model_validate(block.input)
        raise ValueError("Anthropic response did not include the expected tool_use block")
