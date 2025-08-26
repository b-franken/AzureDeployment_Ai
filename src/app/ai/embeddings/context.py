from __future__ import annotations

import contextvars
from dataclasses import dataclass


@dataclass(slots=True)
class EmbeddingsBudget:
    token_limit: int
    call_limit: int
    tokens_used: int = 0
    calls_used: int = 0

    def can_spend(self, tokens: int) -> bool:
        if self.calls_used >= self.call_limit:
            return False
        return self.tokens_used + tokens <= self.token_limit

    def spend(self, tokens: int) -> None:
        self.tokens_used += tokens
        self.calls_used += 1


budget_var: contextvars.ContextVar[EmbeddingsBudget] = contextvars.ContextVar(
    "emb_budget")
req_cache_var: contextvars.ContextVar[dict[str, list[float]]] = contextvars.ContextVar(
    "emb_cache", default={})
