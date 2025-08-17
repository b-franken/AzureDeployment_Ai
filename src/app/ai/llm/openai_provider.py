from __future__ import annotations

from typing import Any, cast

import httpx
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from app.ai.llm.base import LLMProvider
from app.ai.types import Message
from app.core.config import get_settings
from app.core.exceptions import ExternalServiceException, retry_on_error


class OpenAIProvider(LLMProvider):
    def __init__(self) -> None:
        settings = get_settings()
        api_key = (
            settings.llm.openai_api_key.get_secret_value() if settings.llm.openai_api_key else None
        )
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not configured")
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=settings.llm.openai_api_base,
            max_retries=3,
            timeout=httpx.Timeout(60.0, connect=5.0),
        )
        self._default_model = settings.llm.openai_model

    @retry_on_error(max_retries=3, delay=1.0)
    async def chat(self, model: str, messages: list[Message]) -> str:
        try:
            formatted = cast(
                list[ChatCompletionMessageParam],
                [{"role": str(m["role"]), "content": str(m["content"])} for m in messages],
            )
            resp = await self._client.chat.completions.create(
                model=model or self._default_model,
                messages=formatted,
            )
            content = resp.choices[0].message.content or ""
            return content.strip()
        except Exception as err:
            raise ExternalServiceException(f"OpenAI API error: {err}", retryable=True) from err

    @retry_on_error(max_retries=3, delay=1.0)
    async def chat_raw(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = "auto",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        try:
            msg_params = cast(list[ChatCompletionMessageParam], messages)
            kwargs: dict[str, Any] = {
                "model": model or self._default_model,
                "messages": msg_params,
            }
            if tools:
                kwargs["tools"] = tools
                if tool_choice is not None:
                    kwargs["tool_choice"] = tool_choice
            if temperature is not None:
                kwargs["temperature"] = float(temperature)
            if max_tokens is not None:
                kwargs["max_tokens"] = int(max_tokens)
            resp = await self._client.chat.completions.create(**kwargs)
            return resp.model_dump()
        except Exception as err:
            raise ExternalServiceException(f"OpenAI API error: {err}", retryable=True) from err
