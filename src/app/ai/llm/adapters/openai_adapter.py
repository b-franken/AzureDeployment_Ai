from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.ai.types import Message
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class OpenAIAdapter:
    def __init__(self) -> None:
        s = get_settings()
        if not s.llm.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY not configured")
        self._base = s.llm.openai_api_base.rstrip("/")
        self._key = s.llm.openai_api_key.get_secret_value()

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
                    logger.info(f"GPT-5 model '{model}' doesn't support parameter '{k}', skipping")
                    continue

                if k == "temperature" and not is_gpt5 and v == 0:
                    logger.debug(f"Converting temperature=0 to 0.01 for model {model}")
                    out[k] = 0.01
                else:
                    out[k] = v

        if not out.get("stream"):
            out.pop("stream", None)

        logger.debug(f"Sanitized parameters for {model}: {out}")
        return out

    def build_payload(self, model: str, messages: list[Message], **kwargs: Any) -> dict[str, Any]:
        formatted_messages = []
        for m in messages:
            msg = {"role": str(m["role"]), "content": str(m["content"])}

            if "tool_calls" in m:
                msg["tool_calls"] = m["tool_calls"]

            if "tool_call_id" in m:
                msg["tool_call_id"] = m["tool_call_id"]
                msg["role"] = "tool"

            if "name" in m:
                msg["name"] = m["name"]

            formatted_messages.append(msg)

        payload: dict[str, Any] = {
            "model": model,
            "messages": formatted_messages,
        }

        sanitized_kwargs = self._sanitize_kwargs(model, **kwargs)
        payload.update(sanitized_kwargs)

        logger.debug(
            f"Built payload: model={model}, messages_count={len(formatted_messages)}, kwargs={list(sanitized_kwargs.keys())}"
        )

        return payload

    def extract_text(self, data: dict[str, Any]) -> str:
        ch = (data.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        return str(msg.get("content") or "")

    async def stream(
        self, client: httpx.AsyncClient, model: str, messages: list[Message], **kwargs: Any
    ) -> AsyncIterator[str]:
        payload = self.build_payload(model, messages, stream=True, **kwargs)
        async with client.stream(
            "POST", self.endpoint(), json=payload, headers=self.headers()
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                    choice = (obj.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        yield str(piece)
                except Exception:
                    continue

    async def chat_raw(
        self, client: httpx.AsyncClient, model: str, messages: list[dict[str, Any]], **kwargs: Any
    ) -> dict[str, Any]:
        payload = self.build_payload(model, messages, **kwargs)

        # Log the request details for debugging
        logger.info(f"OpenAI API request: model={model}, endpoint={self.endpoint()}")
        logger.debug(f"OpenAI request payload: {json.dumps(payload, indent=2)}")

        resp = await client.post(self.endpoint(), json=payload, headers=self.headers())

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            error_detail = resp.text
            logger.error(f"OpenAI API error {resp.status_code}: {error_detail}")
            logger.error(f"Failed request payload: {json.dumps(payload, indent=2)}")

            try:
                error_json = resp.json()
                if "error" in error_json:
                    error_info = error_json["error"]
                    logger.error(f"OpenAI error details: {json.dumps(error_info, indent=2)}")
            except:
                pass

            raise httpx.HTTPStatusError(
                f"OpenAI API error: {resp.status_code} - {error_detail}",
                request=e.request,
                response=e.response,
            ) from e

        return resp.json()
