from __future__ import annotations

import logging

import httpx

from app.ai.llm.factory import get_provider_and_model
from app.ai.types import ChatHistory, Role
from app.ai.types import Message as AIMessage
from app.core.exceptions import BaseApplicationException
from app.memory.storage import get_async_store

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are DevOpsGPT, an expert in infrastructure, CI/CD, Kubernetes, Terraform,"
    " cloud platforms, monitoring, and automation. "
    "Provide accurate, concise, production-ready guidance."
)


def _msg(role: Role, content: str) -> AIMessage:
    return {"role": role, "content": content}


async def generate_response(
    user_input: str,
    memory: ChatHistory | None = None,
    model: str | None = None,
    provider: str | None = None,
    user_id: str | None = None,
    *,
    thread_id: str | None = None,
    agent: str | None = None,
    history_limit: int = 40,
) -> str:
    store = await get_async_store() if user_id else None
    if memory is None and store and user_id:
        memory_data = await store.get_user_memory(
            user_id=user_id,
            thread_id=thread_id,
            agent=agent,
            limit=history_limit,
        )
        from typing import cast

        memory = cast(ChatHistory, memory_data) if isinstance(memory_data, list) else []

    messages: list[AIMessage] = [_msg("system", SYSTEM_PROMPT)]
    if memory:
        messages.extend(memory)
    messages.append(_msg("user", user_input))

    llm, selected_model = await get_provider_and_model(provider, model)
    logger.debug("llm=%s model=%s", provider or "auto", selected_model)

    try:
        response = await llm.chat(selected_model, messages)
        if store and user_id:
            await store.store_message(
                user_id=user_id,
                role="user",
                content=user_input,
                thread_id=thread_id,
                agent=agent,
                metadata={"source": "generator"},
            )
            await store.store_message(
                user_id=user_id,
                role="assistant",
                content=response,
                thread_id=thread_id,
                agent=agent,
                metadata={"source": "generator"},
            )
        return response
    except BaseApplicationException as err:
        logger.error(
            "LLM provider error",
            extra={"provider": provider or "auto", "model": selected_model, "error": str(err)},
            exc_info=err,
        )
        return err.user_message or "Failed to generate response. Please try again later."
    except httpx.HTTPError as err:
        logger.error(
            "HTTP error while communicating with LLM provider",
            extra={"provider": provider or "auto", "model": selected_model, "error": str(err)},
            exc_info=err,
        )
        return "Failed to connect to the LLM service. Please try again later."
    except Exception as err:
        logger.exception(
            "Unexpected LLM error",
            extra={"provider": provider or "auto", "model": selected_model, "error": str(err)},
        )
        raise
