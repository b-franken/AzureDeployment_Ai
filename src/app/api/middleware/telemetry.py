from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.core.logging import get_logger

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


def _sanitize_attribute_value(value: Any) -> Any:
    """Sanitize attribute values for OpenTelemetry."""

    if value is None:
        return None

    if isinstance(value, bool | int | float | str | bytes):
        return value

    if isinstance(value, list | tuple):
        return [_sanitize_attribute_value(v) for v in value]

    if isinstance(value, dict):
        return {k: _sanitize_attribute_value(v) for k, v in value.items() if not k.startswith("_")}

    return str(value)


def install_telemetry_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def telemetry_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start_time = time.perf_counter()

        with tracer.start_as_current_span(
            f"{request.method} {request.url.path}",
            kind=trace.SpanKind.SERVER,
        ) as span:
            span.set_attributes(
                {
                    "http.method": request.method,
                    "http.url": str(request.url),
                    "http.scheme": request.url.scheme,
                    "http.host": request.url.hostname or "",
                    "http.target": request.url.path,
                    "http.user_agent": request.headers.get("user-agent", ""),
                    "net.peer.ip": request.client.host if request.client else "unknown",
                    "net.peer.port": request.client.port if request.client else 0,
                }
            )

            correlation_id = request.headers.get("x-correlation-id") or request.headers.get(
                "x-request-id"
            )
            if correlation_id:
                span.set_attribute("correlation_id", str(correlation_id))

            auth_header = request.headers.get("authorization", "")
            if auth_header:
                auth_type = auth_header.split()[0] if auth_header else "none"
                span.set_attribute("auth.type", auth_type)

            try:
                response = await call_next(request)

                span.set_attributes(
                    {
                        "http.status_code": response.status_code,
                        "http.status_class": f"{response.status_code // 100}xx",
                    }
                )

                if response.status_code >= 400:
                    span.set_status(Status(StatusCode.ERROR, f"HTTP {response.status_code}"))
                else:
                    span.set_status(Status(StatusCode.OK))

                duration_ms = (time.perf_counter() - start_time) * 1000
                span.set_attribute("http.duration_ms", duration_ms)

                log_extra = {
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                }

                if correlation_id:
                    log_extra["correlation_id"] = str(correlation_id)

                logger.info("Request completed", extra=log_extra)

                return response

            except Exception as exc:
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                span.set_attribute("error.type", type(exc).__name__)
                span.set_attribute("error.message", str(exc))
                span.record_exception(exc)

                log_extra = {
                    "method": request.method,
                    "path": request.url.path,
                    "error": str(exc),
                }

                if correlation_id:
                    log_extra["correlation_id"] = str(correlation_id)

                logger.error("Request failed", extra=log_extra, exc_info=exc)

                raise
