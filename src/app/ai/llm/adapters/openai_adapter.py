from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from opentelemetry import trace

from app.ai.types import Message
from app.core.config import get_settings
from app.core.logging import get_logger
from app.observability.app_insights import app_insights

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


class OpenAIAdapter:
    def __init__(self) -> None:
        s = get_settings()
        if not s.llm.openai_api_key:
            logger.error("OpenAI API key not configured")
            raise RuntimeError("OPENAI_API_KEY not configured")
        self._base = s.llm.openai_api_base.rstrip("/")
        self._key = s.llm.openai_api_key.get_secret_value()
        logger.debug("OpenAI adapter initialized", base_url=self._base)

    def name(self) -> str:
        return "openai"

    def endpoint(self) -> str:
        return f"{self._base}/chat/completions"

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _sanitize_kwargs(self, model: str, **kwargs: Any) -> dict[str, Any]:
        gpt5_unsupported = {
            "temperature",
            "top_p",
            "presence_penalty",
            "frequency_penalty",
            "seed",
            "logit_bias",
            "logprobs",
            "top_logprobs",
        }

        allowed = {
            "temperature",
            "top_p",
            "n",
            "max_tokens",
            "presence_penalty",
            "frequency_penalty",
            "stop",
            "stream",
            "response_format",
            "tools",
            "tool_choice",
            "seed",
            "logit_bias",
            "logprobs",
            "top_logprobs",
        }
        out: dict[str, Any] = {}

        is_gpt5 = model.startswith("gpt-5") or model == "gpt-5"

        for k, v in kwargs.items():
            if k in allowed and v is not None and v != "":
                if is_gpt5 and k in gpt5_unsupported:
                    logger.debug("GPT-5 parameter unsupported, skipping", model=model, parameter=k)
                    continue

                if k == "temperature" and not is_gpt5 and v == 0:
                    logger.debug("Converting temperature=0 to 0.01", model=model)
                    out[k] = 0.01
                else:
                    out[k] = v

        if not out.get("stream"):
            out.pop("stream", None)

        logger.debug("Sanitized OpenAI parameters", model=model, parameters=list(out.keys()))
        return out

    def build_payload(self, model: str, messages: list[Message], **kwargs: Any) -> dict[str, Any]:
        formatted_messages: list[dict[str, Any]] = []
        for m in messages:
            msg: dict[str, Any] = {"role": str(m["role"]), "content": str(m["content"])}

            if "tool_calls" in m and m["tool_calls"]:
                msg["tool_calls"] = m["tool_calls"]

            if "tool_call_id" in m and m["tool_call_id"]:
                msg["tool_call_id"] = m["tool_call_id"]
                msg["role"] = "tool"

            if "name" in m and m["name"]:
                msg["name"] = m["name"]

            formatted_messages.append(msg)

        payload: dict[str, Any] = {
            "model": model,
            "messages": formatted_messages,
        }

        sanitized_kwargs = self._sanitize_kwargs(model, **kwargs)
        payload.update(sanitized_kwargs)

        logger.debug(
            "Built OpenAI request payload",
            model=model,
            messages_count=len(formatted_messages),
            parameters=list(sanitized_kwargs.keys()),
        )

        return payload

    def extract_text(self, data: dict[str, Any]) -> str:
        ch = (data.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        return str(msg.get("content") or "")

    async def stream(
        self, client: httpx.AsyncClient, model: str, messages: list[Message], **kwargs: Any
    ) -> AsyncIterator[str]:
        with tracer.start_as_current_span(
            "openai_stream_request",
            attributes={
                "llm.vendor": "openai",
                "llm.request.model": model,
                "llm.request.type": "stream",
            },
        ) as span:
            payload = self.build_payload(model, messages, stream=True, **kwargs)
            start_time = time.time()

            logger.info("Starting OpenAI stream request", model=model, endpoint=self.endpoint())

            try:
                async with client.stream(
                    "POST", self.endpoint(), json=payload, headers=self.headers()
                ) as r:
                    logger.debug(
                        "OpenAI stream response received",
                        model=model,
                        status_code=r.status_code,
                        response_headers=dict(r.headers),
                    )
                    r.raise_for_status()

                    chunk_count = 0
                    parsed_chunks = 0
                    parse_errors = 0

                    async for line in r.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue

                        data = line.removeprefix("data:").strip()
                        if data == "[DONE]":
                            logger.debug("OpenAI stream completed with [DONE] marker", model=model)
                            break

                        try:
                            obj = json.loads(data)
                            parsed_chunks += 1

                            choice = (obj.get("choices") or [{}])[0]
                            delta = choice.get("delta") or {}
                            piece = delta.get("content")

                            if piece:
                                chunk_count += 1
                                yield str(piece)

                        except json.JSONDecodeError as json_err:
                            parse_errors += 1
                            logger.debug(
                                "Failed to parse stream chunk as JSON",
                                error=str(json_err),
                                data_preview=data[:100],
                                model=model,
                                parse_error_count=parse_errors,
                            )
                            continue
                        except Exception as e:
                            parse_errors += 1
                            logger.debug(
                                "Unexpected error parsing stream chunk",
                                error=str(e),
                                error_type=type(e).__name__,
                                data_preview=data[:100],
                                model=model,
                                parse_error_count=parse_errors,
                            )
                            continue

                    duration_ms = (time.time() - start_time) * 1000
                    span.set_attributes(
                        {
                            "llm.response.chunks": chunk_count,
                            "llm.response.parsed_chunks": parsed_chunks,
                            "llm.response.parse_errors": parse_errors,
                            "llm.response.duration_ms": duration_ms,
                            "llm.response.status_code": r.status_code,
                        }
                    )

                    logger.info(
                        "OpenAI stream request completed successfully",
                        model=model,
                        content_chunks=chunk_count,
                        parsed_chunks=parsed_chunks,
                        parse_errors=parse_errors,
                        duration_ms=duration_ms,
                        status_code=r.status_code,
                    )

                    app_insights.track_custom_event(
                        "openai_stream_completed",
                        {
                            "model": model,
                            "content_chunks": chunk_count,
                            "parsed_chunks": parsed_chunks,
                            "parse_errors": parse_errors,
                            "duration_ms": duration_ms,
                            "status_code": r.status_code,
                        },
                    )

            except httpx.HTTPStatusError as e:
                duration_ms = (time.time() - start_time) * 1000

                # Defensive programming for response attributes
                if hasattr(e, "response") and e.response:
                    status_code = e.response.status_code
                    error_detail = e.response.text
                else:
                    status_code = 0
                    error_detail = "No response available"

                span.record_exception(e)
                span.set_attributes(
                    {
                        "llm.response.error": True,
                        "llm.response.status_code": status_code,
                        "llm.response.duration_ms": duration_ms,
                        "llm.response.error_category": "http_status_error_stream",
                    }
                )

                logger.error(
                    "OpenAI stream request failed with HTTP error",
                    model=model,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    error_detail=(
                        error_detail[:500]
                        if isinstance(error_detail, str)
                        else str(error_detail)[:500]
                    ),
                    error_type="HTTPStatusError",
                    endpoint=self.endpoint(),
                )

                app_insights.track_exception(
                    e,
                    {
                        "model": model,
                        "duration_ms": duration_ms,
                        "status_code": status_code,
                        "error_category": "http_status_error_stream",
                    },
                )
                raise
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                error_type = type(e).__name__
                error_message = str(e)

                span.record_exception(e)
                span.set_attributes(
                    {
                        "llm.response.error": True,
                        "llm.response.duration_ms": duration_ms,
                        "llm.response.error_category": "general_exception_stream",
                        "llm.response.error_type": error_type,
                    }
                )

                logger.error(
                    "OpenAI stream request failed with unexpected exception",
                    model=model,
                    duration_ms=duration_ms,
                    error_type=error_type,
                    error_message=error_message,
                    endpoint=self.endpoint(),
                )

                app_insights.track_exception(
                    e,
                    {
                        "model": model,
                        "duration_ms": duration_ms,
                        "error_category": "general_exception_stream",
                        "error_type": error_type,
                    },
                )
                raise

    async def chat_raw(
        self, client: httpx.AsyncClient, model: str, messages: list[Message], **kwargs: Any
    ) -> dict[str, Any]:
        with tracer.start_as_current_span(
            "openai_chat_request",
            attributes={
                "llm.vendor": "openai",
                "llm.request.model": model,
                "llm.request.type": "chat",
                "llm.request.messages": len(messages),
            },
        ) as span:
            payload = self.build_payload(model, messages, **kwargs)
            start_time = time.time()
            resp: httpx.Response | None = None

            logger.info("Starting OpenAI chat request", model=model, endpoint=self.endpoint())
            logger.debug("OpenAI request payload", payload_keys=list(payload.keys()))

            try:
                resp = await client.post(self.endpoint(), json=payload, headers=self.headers())
                logger.debug(
                    "OpenAI API response received",
                    model=model,
                    status_code=resp.status_code,
                    response_headers=dict(resp.headers),
                )
                resp.raise_for_status()

                response_data: dict[str, Any] = resp.json()
                duration_ms = (time.time() - start_time) * 1000

                usage = response_data.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                total_tokens = usage.get("total_tokens", 0)

                span.set_attributes(
                    {
                        "llm.response.duration_ms": duration_ms,
                        "llm.response.status_code": resp.status_code,
                        "llm.usage.prompt_tokens": prompt_tokens,
                        "llm.usage.completion_tokens": completion_tokens,
                        "llm.usage.total_tokens": total_tokens,
                    }
                )

                logger.info(
                    "OpenAI chat request completed successfully",
                    model=model,
                    duration_ms=duration_ms,
                    status_code=resp.status_code,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                )

                app_insights.track_custom_event(
                    "openai_chat_completed",
                    {
                        "model": model,
                        "duration_ms": duration_ms,
                        "status_code": resp.status_code,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens,
                    },
                )

                return response_data

            except httpx.HTTPStatusError as e:
                duration_ms = (time.time() - start_time) * 1000

                # Defensive programming: resp might not be set if exception occurred during request
                if resp is not None:
                    error_detail = resp.text
                    status_code = resp.status_code
                    error_response: httpx.Response | None = resp
                else:
                    error_detail = "Request failed before receiving response"
                    status_code = (
                        e.response.status_code if hasattr(e, "response") and e.response else 0
                    )
                    error_response = e.response if hasattr(e, "response") else None

                span.record_exception(e)
                span.set_attributes(
                    {
                        "llm.response.error": True,
                        "llm.response.status_code": status_code,
                        "llm.response.duration_ms": duration_ms,
                        "llm.response.error_category": "http_status_error",
                    }
                )

                logger.error(
                    "OpenAI API HTTP error",
                    model=model,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    error_detail=(
                        error_detail[:500] if error_detail else "No error detail available"
                    ),
                    error_type="HTTPStatusError",
                )

                # Enhanced error parsing with defensive programming
                if resp is not None:
                    try:
                        error_json = resp.json()
                        if isinstance(error_json, dict) and "error" in error_json:
                            error_info = error_json["error"]
                            logger.error(
                                "OpenAI API structured error details",
                                error_info=error_info,
                                model=model,
                            )
                            if isinstance(error_info, dict):
                                span.set_attribute(
                                    "llm.response.error_type", error_info.get("type", "unknown")
                                )
                                span.set_attribute(
                                    "llm.response.error_code", error_info.get("code", "unknown")
                                )
                    except Exception as parse_error:
                        logger.debug(
                            "Failed to parse OpenAI error response as JSON",
                            parse_error=str(parse_error),
                            response_content=error_detail[:200] if error_detail else "No content",
                        )

                app_insights.track_exception(
                    e,
                    {
                        "model": model,
                        "status_code": status_code,
                        "duration_ms": duration_ms,
                        "error_category": "http_status_error",
                    },
                )

                # Re-raise with enhanced error information
                error_msg = f"OpenAI API error: {status_code}"
                if error_detail and len(error_detail.strip()) > 0:
                    error_msg += f" - {error_detail[:200]}"

                raise httpx.HTTPStatusError(
                    error_msg,
                    request=e.request,
                    response=error_response or e.response,
                ) from e

            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                error_type = type(e).__name__
                error_message = str(e)

                span.record_exception(e)
                span.set_attributes(
                    {
                        "llm.response.error": True,
                        "llm.response.duration_ms": duration_ms,
                        "llm.response.error_category": "general_exception",
                        "llm.response.error_type": error_type,
                    }
                )

                logger.error(
                    "OpenAI chat request failed with unexpected exception",
                    model=model,
                    duration_ms=duration_ms,
                    error_type=error_type,
                    error_message=error_message,
                    response_received=resp is not None,
                    endpoint=self.endpoint(),
                )

                app_insights.track_exception(
                    e,
                    {
                        "model": model,
                        "duration_ms": duration_ms,
                        "error_category": "general_exception",
                        "error_type": error_type,
                        "response_received": resp is not None,
                    },
                )

                raise
