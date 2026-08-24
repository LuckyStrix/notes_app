from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

SchemaT = TypeVar("SchemaT", bound=BaseModel)


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str


class LLMProvider(ABC):
    """Provider-agnostic interface. Concrete providers normalize their SDK's
    streaming/structured-output shape into this common surface so callers
    (chat endpoint, keyword extraction job) never branch on which provider is
    active.
    """

    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    def chat(self, messages: list[Message], *, system: str | None = None) -> AsyncIterator[str]:
        """Streams incremental text chunks for a chat completion."""

    @abstractmethod
    async def structured_extract(self, prompt: str, schema: type[SchemaT]) -> SchemaT:
        """Single-shot structured extraction, validated against `schema`."""
