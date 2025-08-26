from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ...ai.embeddings.config import EmbeddingsConfig
from ...ai.embeddings.context import EmbeddingsBudget, budget_var, req_cache_var


class EmbeddingsBudgetMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)
        self._cfg = EmbeddingsConfig()

    async def dispatch(self, request: Request, call_next) -> Response:
        if self._cfg.enable:
            budget = EmbeddingsBudget(
                token_limit=self._cfg.req_token_budget, call_limit=self._cfg.req_call_budget)
            token = budget_var.set(budget)
            cache_token = req_cache_var.set({})
            try:
                resp = await call_next(request)
            finally:
                budget_var.reset(token)
                req_cache_var.reset(cache_token)
            return resp
        return await call_next(request)
