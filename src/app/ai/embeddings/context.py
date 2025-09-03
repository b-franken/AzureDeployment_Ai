from __future__ import annotations

import contextvars
from dataclasses import dataclass

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class EmbeddingsBudget:
    token_limit: int
    call_limit: int
    tokens_used: int = 0
    calls_used: int = 0

    def can_spend(self, tokens: int) -> bool:
        if self.calls_used >= self.call_limit:
            logger.debug(
                "Call limit reached",
                calls_used=self.calls_used,
                call_limit=self.call_limit,
            )
            return False
        can_afford = self.tokens_used + tokens <= self.token_limit
        if not can_afford:
            logger.debug(
                "Token limit would be exceeded",
                tokens_used=self.tokens_used,
                token_limit=self.token_limit,
                requested_tokens=tokens,
            )
        return can_afford

    def spend(self, tokens: int) -> None:
        self.tokens_used += tokens
        self.calls_used += 1
        logger.debug(
            "Budget spent",
            tokens=tokens,
            total_tokens=self.tokens_used,
            total_calls=self.calls_used,
        )


budget_var: contextvars.ContextVar[EmbeddingsBudget] = contextvars.ContextVar("emb_budget")
req_cache_var: contextvars.ContextVar[dict[str, list[float]] | None] = contextvars.ContextVar(
    "emb_cache", default=None
)
