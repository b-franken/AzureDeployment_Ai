from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Protocol

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import (
    AuthenticationException,
    AuthorizationException,
    BaseApplicationException,
    CircuitBreakerException,
    ConfigurationException,
    DatabaseException,
    ExternalServiceException,
    RateLimitException,
    ResourceNotFoundException,
    ValidationException,
)
from app.tools.azure.clients import AzureOperationError


class _AzureExceptionsProto(Protocol):
    AzureError: type[Exception]
    ClientAuthenticationError: type[Exception]
    HttpResponseError: type[Exception]
    ServiceRequestError: type[Exception]
    ServiceResponseError: type[Exception]


try:
    # type: ignore[import-not-found]
    import azure.core.exceptions as _azure_mod
except Exception:
    _azure_mod = None  # type: ignore[assignment]

azure_exceptions: _AzureExceptionsProto
if _azure_mod is not None:
    azure_exceptions = SimpleNamespace(
        AzureError=getattr(_azure_mod, "AzureError", Exception),
        ClientAuthenticationError=getattr(_azure_mod, "ClientAuthenticationError", Exception),
        HttpResponseError=getattr(_azure_mod, "HttpResponseError", Exception),
        ServiceRequestError=getattr(_azure_mod, "ServiceRequestError", Exception),
        ServiceResponseError=getattr(_azure_mod, "ServiceResponseError", Exception),
    )
else:

    class _AzureError(Exception):
        pass

    class _ClientAuthenticationError(_AzureError):
        pass

    class _HttpResponseError(_AzureError):
        pass

    class _ServiceRequestError(_AzureError):
        pass

    class _ServiceResponseError(_AzureError):
        pass

    azure_exceptions = SimpleNamespace(
        AzureError=_AzureError,
        ClientAuthenticationError=_ClientAuthenticationError,
        HttpResponseError=_HttpResponseError,
        ServiceRequestError=_ServiceRequestError,
        ServiceResponseError=_ServiceResponseError,
    )

logger = logging.getLogger(__name__)


def _error_response(
    request: Request,
    *,
    status_code: int,
    error_code: str,
    message: str,
    detail: Any = None,
    retry_after: int | float | None = None,
) -> JSONResponse:
    payload: dict[str, Any] = {
        "error_code": error_code,
        "error_message": message,
        "detail": detail,
    }
    headers: dict[str, str] = {}
    corr = request.headers.get("x-correlation-id") or request.headers.get("x-request-id")
    if corr:
        headers["x-correlation-id"] = str(corr)
    if status_code == 429 and retry_after is not None:
        payload["retry_after"] = retry_after
        headers["Retry-After"] = str(int(retry_after))
    return JSONResponse(status_code=status_code, content=payload, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _handle_request_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors: list[dict[str, Any]] = [
            {
                "loc": e.get("loc", []),
                "msg": e.get("msg", "Invalid value"),
                "type": e.get("type", "value_error"),
            }
            for e in exc.errors()
        ]
        logger.warning(
            "Request validation error",
            extra={"error_code": "validation_error", "detail": errors},
        )
        return _error_response(
            request,
            status_code=400,
            error_code="validation_error",
            message="Invalid request",
            detail=errors,
        )

    @app.exception_handler(ValidationError)
    async def _handle_pydantic_validation(request: Request, exc: ValidationError) -> JSONResponse:
        errors: list[dict[str, Any]] = [
            {
                "loc": e.get("loc", []),
                "msg": e.get("msg", "Invalid value"),
                "type": e.get("type", "value_error"),
            }
            for e in exc.errors()
        ]
        logger.warning(
            "Pydantic validation error",
            extra={"error_code": "validation_error", "detail": errors},
        )
        return _error_response(
            request,
            status_code=400,
            error_code="validation_error",
            message="Invalid request",
            detail=errors,
        )

    @app.exception_handler(BaseApplicationException)
    async def _handle_app_exceptions(
        request: Request, exc: BaseApplicationException
    ) -> JSONResponse:
        status_map: dict[type[BaseApplicationException], int] = {
            ValidationException: 400,
            AuthenticationException: 401,
            AuthorizationException: 403,
            ResourceNotFoundException: 404,
            RateLimitException: 429,
            ExternalServiceException: 503,
            DatabaseException: 503,
            ConfigurationException: 500,
            CircuitBreakerException: 503,
        }
        status_code = 500
        for etype, code in status_map.items():
            if isinstance(exc, etype):
                status_code = code
                break
        retry_after = None
        if isinstance(exc, RateLimitException):
            retry_after = (
                int(exc.details.get("retry_after", 0)) if isinstance(exc.details, dict) else None
            )
        level = logging.INFO if status_code == 404 else logging.WARNING
        logger.log(
            level,
            "Application error",
            extra={
                "error_code": exc.__class__.__name__,
                "error_message": str(exc),
                "detail": exc.details,
                "http_status": status_code,
            },
        )
        return _error_response(
            request,
            status_code=status_code,
            error_code=exc.__class__.__name__.replace("Exception", "").lower()
            or "application_error",
            message=exc.user_message or str(exc),
            detail=exc.details,
            retry_after=retry_after,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail_obj: Any = exc.detail
        error_code = "http_error"
        message = "HTTP error"
        if isinstance(detail_obj, dict):
            message = str(detail_obj.get("message") or detail_obj.get("msg") or message)
            error_code = str(detail_obj.get("error_code") or detail_obj.get("error") or error_code)
        elif isinstance(detail_obj, str):
            message = detail_obj
        retry_after = None
        if exc.status_code == 429 and isinstance(detail_obj, dict) and "retry_after" in detail_obj:
            try:
                retry_after = int(detail_obj["retry_after"])
            except Exception:
                retry_after = None
        level = logging.INFO if exc.status_code == 404 else logging.WARNING
        logger.log(
            level,
            "HTTP exception",
            extra={
                "error_code": error_code,
                "error_message": message,
                "detail": detail_obj if isinstance(detail_obj, (dict | list | tuple)) else None,
                "http_status": exc.status_code,
            },
        )
        return _error_response(
            request,
            status_code=exc.status_code,
            error_code=error_code,
            message=message,
            detail=detail_obj if isinstance(detail_obj, (dict | list | tuple)) else None,
            retry_after=retry_after,
        )

    @app.exception_handler(httpx.ConnectTimeout)
    @app.exception_handler(httpx.ReadTimeout)
    async def _handle_httpx_timeout(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "HTTPX timeout",
            extra={"error_code": "network_timeout", "detail": {"type": type(exc).__name__}},
        )
        return _error_response(
            request,
            status_code=504,
            error_code="network_timeout",
            message="Upstream service timed out",
            detail={"type": type(exc).__name__},
        )

    @app.exception_handler(httpx.RequestError)
    async def _handle_httpx_request_error(
        request: Request, exc: httpx.RequestError
    ) -> JSONResponse:
        req_url = str(exc.request.url) if getattr(exc, "request", None) else None
        logger.error(
            "HTTPX request error",
            extra={
                "error_code": "network_error",
                "detail": {"type": type(exc).__name__, "request": req_url},
            },
        )
        return _error_response(
            request,
            status_code=503,
            error_code="network_error",
            message="Upstream network error",
            detail={"type": type(exc).__name__, "request": req_url},
        )

    @app.exception_handler(azure_exceptions.AzureError)
    async def _handle_azure_errors(request: Request, exc: Exception) -> JSONResponse:
        status_code = 500
        error_code = "azure_error"
        message = "Azure SDK error"
        if isinstance(exc, azure_exceptions.ClientAuthenticationError):
            status_code = 401
            error_code = "authentication_error"
            message = "Azure authentication failed"
        elif isinstance(exc, azure_exceptions.ServiceRequestError):
            status_code = 503
            error_code = "service_unavailable"
            message = "Azure service request error"
        elif isinstance(exc, azure_exceptions.ServiceResponseError):
            status_code = 502
            error_code = "bad_gateway"
            message = "Azure service response error"
        elif isinstance(exc, azure_exceptions.HttpResponseError):
            status_code = 502
            error_code = "bad_gateway"
            message = "Azure upstream error"
        logger.error(
            "Azure SDK exception",
            extra={
                "error_code": error_code,
                "error_message": message,
                "detail": {"type": type(exc).__name__, "message": str(exc)},
                "http_status": status_code,
            },
        )
        return _error_response(
            request,
            status_code=status_code,
            error_code=error_code,
            message=message,
            detail={"type": type(exc).__name__, "message": str(exc)},
        )

    @app.exception_handler(AzureOperationError)
    async def _handle_azure_operation_error(
        request: Request, exc: AzureOperationError
    ) -> JSONResponse:
        status_code = (
            502 if exc.retryable else (int(exc.status_code) if exc.status_code is not None else 400)
        )
        detail = {"status_code": exc.status_code, "retryable": exc.retryable}
        level = logging.WARNING if status_code < 500 else logging.ERROR
        logger.log(
            level,
            "Azure operation error",
            extra={"error_code": str(exc.code or "azure_operation_error"), "detail": detail},
        )
        return _error_response(
            request,
            status_code=status_code,
            error_code=str(exc.code or "azure_operation_error"),
            message=str(exc.message or "Azure operation failed"),
            detail=detail,
        )

    @app.exception_handler(Exception)
    async def _handle_uncaught(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled error",
            extra={"error_code": "internal_server_error", "detail": {"type": type(exc).__name__}},
        )
        return _error_response(
            request,
            status_code=500,
            error_code="internal_server_error",
            message="Internal Server Error",
            detail={"type": type(exc).__name__},
        )
