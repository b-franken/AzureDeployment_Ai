from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from opentelemetry import trace

from app.core.loging import add_context, clear_context


def install_correlation_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def _correlation_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-correlation-id") or request.headers.get("x-request-id")
        span = trace.get_current_span()
        trace_id = None
        if span and span.get_span_context() and span.get_span_context().is_valid:
            trace_id = f"{span.get_span_context().trace_id:032x}"
        correlation_id = incoming or trace_id or uuid.uuid4().hex

        add_context(
            correlation_id=correlation_id, path=str(request.url.path), method=request.method
        )
        try:
            if span:
                span.set_attribute("app.correlation_id", correlation_id)
            response = await call_next(request)
            response.headers["x-correlation-id"] = correlation_id
            return response
        finally:
            clear_context()
