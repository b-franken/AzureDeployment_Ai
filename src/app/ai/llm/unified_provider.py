from __future__ import annotations

import json
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
    def __init__(self, adapter: LLMAdapter | list[LLMAdapter] | tuple[LLMAdapter, ...]) -> None:
        # ruff UP038
        self._adapters = tuple(adapter) if isinstance(adapter, list | tuple) else (adapter,)
        self._tracer = trace.get_tracer("llm.unified")
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

    def _sanitize_messages(self, messages: list[Message]) -> list[Message]:
        """Keep only system/user/assistant with string content.
        Drop tool/function messages and assistant messages that contain tool_calls.
        This prevents OpenAI 400: 'tool must be a response to tool_calls'.
        """
        out: list[Message] = []
        for m in messages:
            role = str(m.get("role") or "").lower()
            if role == "tool":
                continue
            if isinstance(m, dict) and ("tool_calls" in m or (role == "assistant" and "name" in m)):
                content = m.get("content")
                if isinstance(content, str) and content.strip():
                    out.append({"role": "assistant", "content": content})
                continue

            content = m.get("content")
            if not isinstance(content, str):
                try:
                    content = json.dumps(content, ensure_ascii=False)
                except Exception:
                    content = "" if content is None else str(content)

            if role not in {"system", "user", "assistant"}:
                role = "user"

            out.append({"role": role, "content": content})
        return out

    @retry_on_error(max_retries=3, base_delay=0.5)
    async def chat(self, model: str, messages: list[Message]) -> str:
        with self._tracer.start_as_current_span("chat") as span:
            span.set_attribute(
                "llm.providers.available", ",".join(a.name() for a in self._adapters)
            )
            span.set_attribute("llm.provider.primary", self._adapters[0].name())
            clean = self._sanitize_messages(messages)
            last_err: Exception | None = None

            for idx, adapter in enumerate(self._adapters):
                with self._tracer.start_as_current_span(f"{adapter.name()}.attempt") as attempt:
                    attempt.set_attribute("llm.provider", adapter.name())
                    attempt.set_attribute("llm.model.requested", model)
                    try:
                        payload = adapter.build_payload(model, clean)
                        resp = await self._client.post(
                            adapter.endpoint(), json=payload, headers=adapter.headers()
                        )
                        resp.raise_for_status()
                        text = adapter.extract_text(resp.json()).strip()
                        span.set_attribute("llm.provider.used", adapter.name())
                        span.set_attribute("llm.fallback_used", bool(idx > 0))
                        return text
                    except Exception as err:
                        attempt.record_exception(err)
                        attempt.set_status(Status(StatusCode.ERROR, str(err)))
                        last_err = err
                        continue

            current = trace.get_current_span()
            if current and last_err is not None:
                current.record_exception(last_err)
                current.set_status(Status(StatusCode.ERROR, str(last_err)))
            raise ExternalServiceException("LLM service unavailable", retryable=True)

    @retry_on_error(max_retries=2, base_delay=0.5)
    async def chat_stream(
        self, model: str, messages: list[Message], **kwargs: Any
    ) -> AsyncIterator[str]:
        with self._tracer.start_as_current_span("chat.stream") as span:
            span.set_attribute(
                "llm.providers.available", ",".join(a.name() for a in self._adapters)
            )
            span.set_attribute("llm.provider.primary", self._adapters[0].name())
            clean = self._sanitize_messages(messages)
            last_err: Exception | None = None

            for idx, adapter in enumerate(self._adapters):
                with self._tracer.start_as_current_span(f"{adapter.name()}.attempt") as attempt:
                    attempt.set_attribute("llm.provider", adapter.name())
                    attempt.set_attribute("llm.model.requested", model)
                    agen: AsyncIterator[str] | None = None
                    try:
                        agen = adapter.stream(self._client, model, clean, **kwargs)
                        # type: ignore[attr-defined]
                        first = await agen.__anext__()
                        span.set_attribute("llm.provider.used", adapter.name())
                        span.set_attribute("llm.fallback_used", bool(idx > 0))
                        yield first
                        async for piece in agen:
                            yield piece
                        yield ""
                        return
                    except StopAsyncIteration:
                        span.set_attribute("llm.provider.used", adapter.name())
                        span.set_attribute("llm.fallback_used", bool(idx > 0))
                        yield ""
                        return
                    except Exception as err:
                        attempt.record_exception(err)
                        attempt.set_status(Status(StatusCode.ERROR, str(err)))
                        last_err = err
                        continue

            current = trace.get_current_span()
            if current and last_err is not None:
                current.record_exception(last_err)
                current.set_status(Status(StatusCode.ERROR, str(last_err)))
            raise ExternalServiceException("LLM service unavailable", retryable=True)

    @retry_on_error(max_retries=3, base_delay=0.5)
    async def chat_raw(
        self, model: str, messages: list[dict[str, Any]], **kwargs: Any
    ) -> dict[str, Any]:
        with self._tracer.start_as_current_span("chat.raw") as span:
            span.set_attribute(
                "llm.providers.available", ",".join(a.name() for a in self._adapters)
            )
            span.set_attribute("llm.provider.primary", self._adapters[0].name())
            clean: list[dict[str, Any]] = [
                {"role": m.get("role"), "content": m.get("content")}
                # type: ignore[arg-type]
                for m in self._sanitize_messages(messages)
            ]

            last_err: Exception | None = None
            for idx, adapter in enumerate(self._adapters):
                with self._tracer.start_as_current_span(f"{adapter.name()}.attempt") as attempt:
                    attempt.set_attribute("llm.provider", adapter.name())
                    attempt.set_attribute("llm.model.requested", model)
                    try:
                        out = await adapter.chat_raw(self._client, model, clean, **kwargs)
                        span.set_attribute("llm.provider.used", adapter.name())
                        span.set_attribute("llm.fallback_used", bool(idx > 0))
                        return out
                    except Exception as err:
                        attempt.record_exception(err)
                        attempt.set_status(Status(StatusCode.ERROR, str(err)))
                        last_err = err
                        continue

            current = trace.get_current_span()
            if current and last_err is not None:
                current.record_exception(last_err)
                current.set_status(Status(StatusCode.ERROR, str(last_err)))
            raise ExternalServiceException("LLM service unavailable", retryable=True)
