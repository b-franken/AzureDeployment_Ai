from __future__ import annotations

import logging

import httpx

from app.ai.llm.factory import get_provider_and_model
from app.ai.types import ChatHistory
from app.ai.types import Message as AIMessage
from app.core.exceptions import BaseApplicationException

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are DevOpsGPT, an expert in infrastructure, CI/CD, Kubernetes, Terraform, "
    "cloud platforms, monitoring, and automation. Provide accurate, concise, "
    "production-ready guidance."
)


def _msg(role: str, content: str) -> AIMessage:
    return {"role": role, "content": content}


async def generate_response(
    user_input: str,
    memory: ChatHistory | None = None,
    model: str | None = None,
    provider: str | None = None,
) -> str:
    messages: list[AIMessage] = [_msg("system", SYSTEM_PROMPT)]
    if memory:
        messages.extend(memory)
    messages.append(_msg("user", user_input))

    llm, selected_model = await get_provider_and_model(provider, model)
    logger.debug("llm=%s model=%s", provider or "auto", selected_model)
    try:
        return await llm.chat(selected_model, messages)
    except BaseApplicationException as err:
        logger.error(
            "LLM provider error",
            extra={
                "provider": provider or "auto",
                "model": selected_model,
                "error": str(err),
            },
            exc_info=err,
        )
        return err.user_message or "Failed to generate response. Please try again later."
    except httpx.HTTPError as err:
        logger.error(
            "HTTP error while communicating with LLM provider",
            extra={
                "provider": provider or "auto",
                "model": selected_model,
                "error": str(err),
            },
            exc_info=err,
        )
        return "Failed to connect to the LLM service. Please try again later."
    except Exception as err:
        logger.exception(
            "Unexpected LLM error",
            extra={
                "provider": provider or "auto",
                "model": selected_model,
                "error": str(err),
            },
        )
        raise
