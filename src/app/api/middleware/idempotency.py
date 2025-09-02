import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class IdempotencyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, window_seconds: int = 30) -> None:
        super().__init__(app)
        self._window = window_seconds
        self._inflight: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method == "POST" and request.url.path == "/api/chat":
            body = await request.body()
            digest = hashlib.blake2b(body, digest_size=16).hexdigest()
            async with self._lock:
                if digest in self._inflight:
                    return JSONResponse({"status": "duplicate"}, status_code=202)
                self._inflight[digest] = asyncio.get_event_loop().time()
            try:
                return await call_next(request)
            finally:
                async with self._lock:
                    self._inflight.pop(digest, None)
        return await call_next(request)
