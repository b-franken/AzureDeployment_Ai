from __future__ import annotations

import abc
from collections.abc import AsyncIterator
from typing import Any

from app.ai.types import Message


class LLMProvider(abc.ABC):
    @abc.abstractmethod
    async def chat(self, model: str, messages: list[Message]) -> str: ...

    @abc.abstractmethod
    async def chat_stream(self, model: str, messages: list[Message]) -> AsyncIterator[str]: ...

    @abc.abstractmethod
    async def chat_raw(
        self,
        model: str,
        messages: list[Message],
        tool_choice: str | dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any: ...
