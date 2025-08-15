from __future__ import annotations

from app.ai.generator import generate_response

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
    prompt = f"{REVIEW_PROMPT}\n\n---\nUser: {user_input}\nAssistant: {assistant_reply}"
    return await generate_response(prompt, memory=[], model=model, provider=provider)
