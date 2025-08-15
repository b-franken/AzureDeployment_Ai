from __future__ import annotations

import abc

from app.ai.types import Message


class LLMProvider(abc.ABC):
    @abc.abstractmethod
    async def chat(self, model: str, messages: list[Message]) -> str: ...
