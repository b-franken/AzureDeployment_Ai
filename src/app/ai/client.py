from __future__ import annotations

from functools import lru_cache

from openai import AsyncOpenAI

from app.config import OPENAI_API_KEY


@lru_cache
def get_client() -> AsyncOpenAI:
    key = OPENAI_API_KEY
    if not key:
        raise RuntimeError("OPENAI_API_KEY must be set")
    return AsyncOpenAI(api_key=key)
