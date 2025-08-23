from __future__ import annotations

from collections.abc import AsyncIterator
from types import TracebackType
from typing import Any, Protocol, runtime_checkable

import httpx
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.ai.llm.base import LLMProvider
from app.ai.types import Message
from app.core.exceptions import ExternalServiceException, retry_on_error


@runtime_checkable
class LLMAdapter(Protocol):
    def name(self) -> str: ...
    def endpoint(self) -> str: ...
    def headers(self) -> dict[str, str]: ...
    def build_payload(
        self, model: str, messages: list[Message], **kwargs: Any
    ) -> dict[str, Any]: ...

    def extract_text(self, data: dict[str, Any]) -> str: ...

    def stream(
        self, client: httpx.AsyncClient, model: str, messages: list[Message], **kwargs: Any
    ) -> AsyncIterator[str]: ...

    async def chat_raw(
        self, client: httpx.AsyncClient, model: str, messages: list[dict[str, Any]], **kwargs: Any
    ) -> dict[str, Any]: ...


class UnifiedLLMProvider(LLMProvider):
    def __init__(self, adapter: LLMAdapter) -> None:
        self._adapter = adapter
        self._tracer = trace.get_tracer(f"llm.{adapter.name()}")
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> UnifiedLLMProvider:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    @retry_on_error(max_retries=3, base_delay=0.5)
    async def chat(self, model: str, messages: list[Message]) -> str:
        with self._tracer.start_as_current_span(f"{self._adapter.name()}.chat") as span:
            span.set_attribute("llm.provider", self._adapter.name())
            span.set_attribute("llm.model.requested", model)
            try:
                payload = self._adapter.build_payload(model, messages)
                resp = await self._client.post(
                    self._adapter.endpoint(), json=payload, headers=self._adapter.headers()
                )
                resp.raise_for_status()
                text = self._adapter.extract_text(resp.json())
                return text.strip()
            except Exception as err:
                current = trace.get_current_span()
                if current:
                    current.record_exception(err)
                    current.set_status(Status(StatusCode.ERROR, str(err)))
                raise ExternalServiceException("LLM service unavailable", retryable=True) from err

    @retry_on_error(max_retries=2, base_delay=0.5)
    async def chat_stream(
        self, model: str, messages: list[Message], **kwargs: Any
    ) -> AsyncIterator[str]:
        with self._tracer.start_as_current_span(f"{self._adapter.name()}.chat.stream") as span:
            span.set_attribute("llm.provider", self._adapter.name())
            span.set_attribute("llm.model.requested", model)
            try:
                stream = self._adapter.stream(self._client, model, messages, **kwargs)
                async for piece in stream:
                    yield piece
            except Exception as err:
                current = trace.get_current_span()
                if current:
                    current.record_exception(err)
                    current.set_status(Status(StatusCode.ERROR, str(err)))
                raise ExternalServiceException("LLM service unavailable", retryable=True) from err
            yield ""

    @retry_on_error(max_retries=3, base_delay=0.5)
    async def chat_raw(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        with self._tracer.start_as_current_span(f"{self._adapter.name()}.chat.raw") as span:
            span.set_attribute("llm.provider", self._adapter.name())
            span.set_attribute("llm.model.requested", model)
            try:
                return await self._adapter.chat_raw(self._client, model, messages, **kwargs)
            except Exception as err:
                current = trace.get_current_span()
                if current:
                    current.record_exception(err)
                    current.set_status(Status(StatusCode.ERROR, str(err)))
                raise ExternalServiceException("LLM service unavailable", retryable=True) from err
