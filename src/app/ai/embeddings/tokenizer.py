from __future__ import annotations

from collections.abc import Iterable

from app.core.logging import get_logger

try:
    import tiktoken
except Exception:  # noqa: BLE001
    tiktoken = None  # type: ignore[assignment]

logger = get_logger(__name__)


def estimate_tokens(texts: Iterable[str]) -> int:
    text_list = list(texts)
    if tiktoken is None:
        logger.debug("tiktoken not available, using fallback estimation", text_count=len(text_list))
        return sum(max(1, len(t) // 4) for t in text_list)
    
    logger.debug("Estimating tokens with tiktoken", text_count=len(text_list))
    enc = tiktoken.get_encoding("cl100k_base")
    token_count = sum(len(enc.encode(t)) for t in text_list)
    logger.debug("Token estimation completed", total_tokens=token_count)
    return token_count
