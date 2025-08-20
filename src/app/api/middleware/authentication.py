from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import jwt
from fastapi import FastAPI, Request, Response

logger = logging.getLogger(__name__)


def install_auth_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def auth_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.user_id = None
        auth_header = request.headers.get("authorization") or ""
        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1]
            try:
                payload = jwt.decode(token, options={"verify_signature": False})
                user_id = payload.get("oid") or payload.get("sub") or payload.get("user_id")
                if isinstance(user_id, str) and user_id:
                    request.state.user_id = user_id
            except jwt.PyJWTError as exc:
                logger.debug("Failed to decode JWT token: %s", exc)
        return await call_next(request)
