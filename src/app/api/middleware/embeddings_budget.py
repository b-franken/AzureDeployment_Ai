from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from ...ai.embeddings.config import EmbeddingsConfig
from ...ai.embeddings.context import EmbeddingsBudget, budget_var, req_cache_var


def install_embeddings_budget_middleware(app: FastAPI) -> None:
    cfg = EmbeddingsConfig()

    @app.middleware("http")
    async def embeddings_budget_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if cfg.enable:
            budget = EmbeddingsBudget(
                token_limit=cfg.req_token_budget, call_limit=cfg.req_call_budget
            )
            token = budget_var.set(budget)
            cache_token = req_cache_var.set({})
            try:
                resp = await call_next(request)
            finally:
                budget_var.reset(token)
                req_cache_var.reset(cache_token)
            return resp
        return await call_next(request)
