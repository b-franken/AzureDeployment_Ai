from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

logger = logging.getLogger(__name__)


def _is_azure_error(exc: BaseException) -> bool:
    mod = getattr(exc.__class__, "__module__", "")
    return mod.startswith("azure.")


async def safe_get(
    callable_obj: Callable[..., Any] | Awaitable[Any],
    *args: Any,
    **kwargs: Any,
) -> tuple[bool, Any]:
    try:
        if callable(callable_obj):
            func = cast("Callable[..., Any]", callable_obj)
            result = func(*args, **kwargs)
            if inspect.isawaitable(result):
                res = await cast("Awaitable[Any]", result)
            else:
                res = await asyncio.to_thread(func, *args, **kwargs)
        elif inspect.isawaitable(callable_obj):
            res = await cast("Awaitable[Any]", callable_obj)
        else:
            raise TypeError("safe_get expects a callable or awaitable")
        return True, res
    except Exception as exc:
        level = logger.warning if _is_azure_error(exc) else logger.error
        level(
            "azure_idempotency.safe_get.error",
            extra={
                "callable": getattr(callable_obj, "__name__", type(callable_obj).__name__),
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "azure_error": _is_azure_error(exc),
            },
            exc_info=True,
        )
        return False, None


SENSITIVE_KEYS = (
    "AccountKey",
    "SharedAccessKey",
    "PrimaryKey",
    "SecondaryKey",
    "connectionstring",
    "authorization",
    "token",
    "pat",
)


def redact(text: str) -> str:
    lower = text.lower()
    for key in SENSITIVE_KEYS:
        if key.lower() in lower:
            return "[redacted]"
    return text
