from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request, Response

from app.core.logging import add_context, clear_context, get_logger


def instrument_correlation(app: FastAPI, header_name: str = "x-request-id") -> None:
    logger = get_logger("correlation")

    @app.middleware("http")
    async def _cid_mw(request: Request, call_next):
        cid = request.headers.get(header_name) or str(uuid4())
        add_context(correlation_id=cid)
        try:
            response: Response = await call_next(request)
            response.headers[header_name] = cid
            logger.info(
                "request_completed",
                method=request.method,
                path=str(request.url.path),
                correlation_id=cid,
                status=response.status_code,
            )
            return response
        finally:
            clear_context()
