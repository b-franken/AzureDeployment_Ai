import logging
from typing import Awaitable, Callable

import fastapi
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.testclient import TestClient

logger = logging.getLogger(__name__)


class DummyLimiter:
    async def check_rate_limit(
        self, request: Request, user_id: str | None = None
    ) -> None:  # pragma: no cover - stub
        return None


limiter = DummyLimiter()
app = FastAPI()


@app.middleware("http")
async def _rl_mw(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    user_id = getattr(request.state, "user_id", None)
    await limiter.check_rate_limit(request, user_id)
    try:
        return await call_next(request)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Middleware error")
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc


@app.get("/error")
async def _error() -> None:
    raise RuntimeError("boom")


client = TestClient(app, raise_server_exceptions=False)


def test_middleware_returns_500_on_exception() -> None:
    resp = client.get("/error")
    assert resp.status_code == 500
    major, minor, *_ = fastapi.__version__.split(".")
    if int(major) > 0 or int(minor) >= 112:
        try:
            assert resp.json() == {"detail": "Internal Server Error"}
        except ValueError:
            assert resp.text == "Internal Server Error"
    else:
        assert resp.text == "Internal Server Error"
