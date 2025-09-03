from __future__ import annotations

import json
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Any, Protocol, cast, runtime_checkable

import httpx
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.ai.llm.base import LLMProvider
from app.ai.types import Message
from app.ai.validation import LLMMessage, MessageRole, ValidationResult
from app.core.exceptions import ExternalServiceException, retry_on_error
from app.core.logging import get_logger

logger = get_logger(__name__)


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
        self, client: httpx.AsyncClient, model: str, messages: list[Message], **kwargs: Any
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

    def _sanitize_messages(self, messages: list[Message]) -> ValidationResult:
        """Validate and sanitize messages using Pydantic models."""
        sanitized: list[LLMMessage] = []
        errors: list[str] = []
        warnings: list[str] = []

        for i, m in enumerate(messages):
            try:
                role = str(m.get("role") or "").lower()

                if role == "tool":
                    warnings.append(f"Message {i}: Skipping tool message")
                    continue

                if isinstance(m, dict) and (
                    "tool_calls" in m or (role == "assistant" and "name" in m)
                ):
                    content = m.get("content")
                    if isinstance(content, str) and content.strip():
                        sanitized.append(LLMMessage(role=MessageRole.ASSISTANT, content=content))
                        warnings.append(f"Message {i}: Stripped tool_calls from assistant message")
                    else:
                        warnings.append(
                            f"Message {i}: Skipping assistant message with "
                            "tool_calls and no content"
                        )
                    continue

                content = m.get("content")
                if not isinstance(content, str):
                    try:
                        content = json.dumps(content, ensure_ascii=False)
                        warnings.append(f"Message {i}: Converted non-string content to JSON")
                    except Exception:
                        content = "" if content is None else str(content)
                        warnings.append(f"Message {i}: Converted content to string")

                try:
                    message_role = (
                        MessageRole(role)
                        if role in {"system", "user", "assistant"}
                        else MessageRole.USER
                    )
                    if role not in {"system", "user", "assistant"}:
                        warnings.append(f"Message {i}: Unknown role '{role}', using 'user'")

                    sanitized.append(LLMMessage(role=message_role, content=content))
                except ValueError as e:
                    errors.append(f"Message {i}: Invalid role '{role}': {e}")

            except Exception as e:
                errors.append(f"Message {i}: Validation error: {e}")

        if errors:
            return ValidationResult.failure(errors, warnings)

        return ValidationResult.success(sanitized)

    @retry_on_error(max_retries=3, base_delay=0.5)
    async def chat(self, model: str, messages: list[Message]) -> str:
        with self._tracer.start_as_current_span("chat") as span:
            span.set_attribute(
                "llm.providers.available", ",".join(a.name() for a in self._adapters)
            )
            span.set_attribute("llm.provider.primary", self._adapters[0].name())

            validation = self._sanitize_messages(messages)
            if not validation.is_valid:
                raise ValueError(f"Message validation failed: {'; '.join(validation.errors)}")

            if validation.warnings:
                current = trace.get_current_span()
                if current:
                    current.add_event(
                        "message_validation_warnings", {"warnings": validation.warnings}
                    )

            clean_messages: list[Message] = [
                cast(Message, {"role": m.role.value, "content": m.content})
                for m in validation.sanitized_messages
            ]
            last_err: Exception | None = None

            logger.debug(f"Processing {len(clean_messages)} messages for model {model}")
            logger.debug(f"Available adapters: {[a.name() for a in self._adapters]}")

            for idx, adapter in enumerate(self._adapters):
                with self._tracer.start_as_current_span(f"{adapter.name()}.attempt") as attempt:
                    attempt.set_attribute("llm.provider", adapter.name())
                    attempt.set_attribute("llm.model.requested", model)
                    logger.debug(
                        f"Attempting chat with adapter {adapter.name()} (attempt {idx + 1})"
                    )
                    try:
                        payload = adapter.build_payload(model, clean_messages)
                        resp = await self._client.post(
                            adapter.endpoint(), json=payload, headers=adapter.headers()
                        )
                        resp.raise_for_status()
                        text = adapter.extract_text(resp.json()).strip()
                        span.set_attribute("llm.provider.used", adapter.name())
                        span.set_attribute("llm.fallback_used", bool(idx > 0))
                        logger.info(
                            f"Successfully completed chat with {adapter.name()}, "
                            f"response length: {len(text)}"
                        )
                        return text
                    except Exception as err:
                        logger.warning(f"Chat failed with adapter {adapter.name()}: {err}")
                        attempt.record_exception(err)
                        attempt.set_status(Status(StatusCode.ERROR, str(err)))
                        last_err = err
                        continue

            logger.error(f"All LLM adapters failed for chat request, last error: {last_err}")
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

            validation = self._sanitize_messages(messages)
            if not validation.is_valid:
                raise ValueError(f"Message validation failed: {'; '.join(validation.errors)}")

            if validation.warnings:
                current = trace.get_current_span()
                if current:
                    current.add_event(
                        "message_validation_warnings", {"warnings": validation.warnings}
                    )

            clean_messages: list[Message] = [
                cast(Message, {"role": m.role.value, "content": m.content})
                for m in validation.sanitized_messages
            ]
            last_err: Exception | None = None

            logger.debug(
                f"Processing streaming request with {len(clean_messages)} messages "
                f"for model {model}"
            )
            logger.debug(f"Available adapters: {[a.name() for a in self._adapters]}")

            for idx, adapter in enumerate(self._adapters):
                with self._tracer.start_as_current_span(f"{adapter.name()}.attempt") as attempt:
                    attempt.set_attribute("llm.provider", adapter.name())
                    attempt.set_attribute("llm.model.requested", model)
                    logger.debug(
                        f"Attempting stream with adapter {adapter.name()} (attempt {idx + 1})"
                    )
                    agen: AsyncIterator[str] | None = None
                    try:
                        agen = adapter.stream(self._client, model, clean_messages, **kwargs)
                        first = await agen.__anext__()
                        span.set_attribute("llm.provider.used", adapter.name())
                        span.set_attribute("llm.fallback_used", bool(idx > 0))
                        logger.info(f"Successfully started streaming with {adapter.name()}")
                        yield first
                        async for piece in agen:
                            yield piece
                        yield ""
                        logger.debug(f"Completed streaming with {adapter.name()}")
                        return
                    except StopAsyncIteration:
                        span.set_attribute("llm.provider.used", adapter.name())
                        span.set_attribute("llm.fallback_used", bool(idx > 0))
                        logger.debug(f"Stream completed immediately for {adapter.name()}")
                        yield ""
                        return
                    except Exception as err:
                        logger.warning(f"Streaming failed with adapter {adapter.name()}: {err}")
                        attempt.record_exception(err)
                        attempt.set_status(Status(StatusCode.ERROR, str(err)))
                        last_err = err
                        continue

            logger.error(f"All LLM adapters failed for streaming request, last error: {last_err}")
            current = trace.get_current_span()
            if current and last_err is not None:
                current.record_exception(last_err)
                current.set_status(Status(StatusCode.ERROR, str(last_err)))
            raise ExternalServiceException("LLM service unavailable", retryable=True)

    @retry_on_error(max_retries=3, base_delay=0.5)
    async def chat_raw(
        self,
        model: str,
        messages: list[Message],
        tool_choice: str | dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        with self._tracer.start_as_current_span("chat.raw") as span:
            span.set_attribute(
                "llm.providers.available", ",".join(a.name() for a in self._adapters)
            )
            span.set_attribute("llm.provider.primary", self._adapters[0].name())

            validation = self._sanitize_messages(messages)
            if not validation.is_valid:
                raise ValueError(f"Message validation failed: {'; '.join(validation.errors)}")

            if validation.warnings:
                current = trace.get_current_span()
                if current:
                    current.add_event(
                        "message_validation_warnings", {"warnings": validation.warnings}
                    )

            from app.ai.types import Role

            clean: list[Message] = []
            for m in validation.sanitized_messages:
                role_value: Role = m.role.value
                message: Message = {"role": role_value, "content": m.content}
                if m.tool_calls:
                    message["tool_calls"] = m.tool_calls
                if m.name:
                    message["name"] = m.name
                clean.append(message)

            logger.debug(
                f"Processing raw chat request with {len(clean)} messages for model {model}"
            )
            logger.debug(f"Available adapters: {[a.name() for a in self._adapters]}")

            last_err: Exception | None = None
            for idx, adapter in enumerate(self._adapters):
                with self._tracer.start_as_current_span(f"{adapter.name()}.attempt") as attempt:
                    attempt.set_attribute("llm.provider", adapter.name())
                    attempt.set_attribute("llm.model.requested", model)
                    logger.debug(
                        f"Attempting raw chat with adapter {adapter.name()} (attempt {idx + 1})"
                    )
                    try:
                        out = await adapter.chat_raw(self._client, model, clean, **kwargs)
                        span.set_attribute("llm.provider.used", adapter.name())
                        span.set_attribute("llm.fallback_used", bool(idx > 0))
                        logger.info(f"Successfully completed raw chat with {adapter.name()}")
                        return out
                    except Exception as err:
                        logger.warning(f"Raw chat failed with adapter {adapter.name()}: {err}")
                        attempt.record_exception(err)
                        attempt.set_status(Status(StatusCode.ERROR, str(err)))
                        last_err = err
                        continue

            logger.error(f"All LLM adapters failed for raw chat request, last error: {last_err}")
            current = trace.get_current_span()
            if current and last_err is not None:
                current.record_exception(last_err)
                current.set_status(Status(StatusCode.ERROR, str(last_err)))
            raise ExternalServiceException("LLM service unavailable", retryable=True)
