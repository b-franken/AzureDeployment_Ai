from __future__ import annotations

from app.ai.generator import generate_response
from app.core.logging import get_logger

logger = get_logger(__name__)

REVIEW_PROMPT = (
    "You are a senior DevOps engineer reviewing the assistant’s answer. "
    "Inspect for correctness, production readiness, and clarity. "
    "Point out mistakes and risks; improve if necessary.\n\n"
    "Use this format:\n"
    "Score: x/10\n"
    "Review:\n<analysis>\n\n"
    "Corrected/Improved Answer:\n<content if needed>"
)


async def senior_review(
    user_input: str,
    assistant_reply: str,
    model: str | None = None,
    provider: str | None = None,
) -> str:
    logger.info(
        "Starting senior review",
        model=model,
        provider=provider,
        user_input_length=len(user_input),
        assistant_reply_length=len(assistant_reply),
    )
    prompt = f"{REVIEW_PROMPT}\n\n---\nUser: {user_input}\nAssistant: {assistant_reply}"
    logger.debug("Generated review prompt", prompt_length=len(prompt))

    try:
        review_result = await generate_response(prompt, memory=[], model=model, provider=provider)
        logger.info("Senior review completed successfully", review_length=len(review_result))
        return review_result
    except Exception as e:
        logger.error("Senior review failed", error=str(e), error_type=type(e).__name__)
        raise
