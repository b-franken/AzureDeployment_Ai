from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, cast

import httpx
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

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
        self._tracer = trace.get_tracer("llm.openai")

    def list_models(self) -> list[str]:
        try:
            import asyncio

            async def _do() -> list[str]:
                resp = await self._client.models.list()
                return [m.id for m in resp.data if getattr(m, "id", None)]

            return asyncio.get_event_loop().run_until_complete(_do())
        except Exception:
            return ["gpt-4o-mini", "gpt-4o", "gpt-5"]

    @retry_on_error(max_retries=3, delay=1.0)
    async def chat(self, model: str, messages: list[Message]) -> str:
        with self._tracer.start_as_current_span("openai.chat.completions") as span:
            span.set_attribute("llm.provider", "openai")
            span.set_attribute("llm.endpoint", "chat.completions")
            span.set_attribute("llm.model.requested", model or self._default_model)
            try:
                formatted = cast(
                    list[ChatCompletionMessageParam],
                    [{"role": str(m["role"]), "content": str(m["content"])} for m in messages],
                )
                resp = await self._client.chat.completions.create(
                    model=model or self._default_model,
                    messages=formatted,
                )
                usage = getattr(resp, "usage", None)
                if usage is not None:
                    span.set_attribute("llm.tokens.prompt", getattr(usage, "prompt_tokens", 0))
                    span.set_attribute(
                        "llm.tokens.completion", getattr(usage, "completion_tokens", 0)
                    )
                    span.set_attribute("llm.tokens.total", getattr(usage, "total_tokens", 0))
                content = resp.choices[0].message.content or ""
                return content.strip()
            except Exception as err:
                current = trace.get_current_span()
                if current:
                    current.record_exception(err)
                    current.set_status(Status(StatusCode.ERROR, str(err)))
                raise ExternalServiceException(
                    "The AI service is busy or unreachable. Please retry. If this keeps happening, "
                    "try a smaller prompt or wait a minute.",
                    retryable=True,
                ) from err

    @retry_on_error(max_retries=3, delay=1.0)
    async def chat_raw(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = "auto",
        temperature: float | None = None,
        max_tokens: int | None = None,
        # JSON mode or JSON Schema
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._tracer.start_as_current_span("openai.chat.completions.raw") as span:
            span.set_attribute("llm.provider", "openai")
            span.set_attribute("llm.endpoint", "chat.completions")
            span.set_attribute("llm.model.requested", model or self._default_model)
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
                if response_format:
                    kwargs["response_format"] = response_format
                if temperature is not None:
                    kwargs["temperature"] = float(temperature)
                if max_tokens is not None:
                    kwargs["max_tokens"] = int(max_tokens)

                resp = await self._client.chat.completions.create(**kwargs)

                usage = getattr(resp, "usage", None)
                if usage is not None:
                    span.set_attribute("llm.tokens.prompt", getattr(usage, "prompt_tokens", 0))
                    span.set_attribute(
                        "llm.tokens.completion", getattr(usage, "completion_tokens", 0)
                    )
                    span.set_attribute("llm.tokens.total", getattr(usage, "total_tokens", 0))

                return resp.model_dump()
            except Exception as err:
                current = trace.get_current_span()
                if current:
                    current.record_exception(err)
                    current.set_status(Status(StatusCode.ERROR, str(err)))
                raise ExternalServiceException(
                    "The AI service is busy or unreachable. Please retry. If this keeps happening,"
                    " try a smaller prompt or wait a minute.",
                    retryable=True,
                ) from err

    @retry_on_error(max_retries=2, delay=0.5)
    async def chat_stream(
        self, model: str, messages: list[Message], temperature: float | None = None
    ) -> AsyncGenerator[str, None]:
        with self._tracer.start_as_current_span("openai.chat.completions.stream") as span:
            span.set_attribute("llm.provider", "openai")
            span.set_attribute("llm.endpoint", "chat.completions")
            span.set_attribute("llm.model.requested", model or self._default_model)
            try:
                formatted = cast(
                    list[ChatCompletionMessageParam],
                    [{"role": str(m["role"]), "content": str(m["content"])} for m in messages],
                )
                kwargs: dict[str, Any] = {
                    "model": model or self._default_model,
                    "messages": formatted,
                    "stream": True,
                }
                if temperature is not None:
                    kwargs["temperature"] = float(temperature)
                # type: ignore[arg-type]
                stream = await self._client.chat.completions.create(**kwargs)
                async for event in stream:
                    try:
                        ch = event.choices[0]
                        piece = getattr(ch.delta, "content", None)
                        if piece:
                            yield str(piece)
                    except Exception:
                        continue
                yield ""
            except Exception as err:
                current = trace.get_current_span()
                if current:
                    current.record_exception(err)
                    current.set_status(Status(StatusCode.ERROR, str(err)))
                raise
