from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

try:  # pragma: no cover - safety net if Azure SDK is absent
    from azure.core.exceptions import AzureError
except Exception:  # pragma: no cover - Azure not installed
    AzureError = Exception

logger = logging.getLogger(__name__)


async def safe_get(callable_obj: Callable[..., Any], *args: Any, **kwargs: Any) -> tuple[bool, Any]:
    try:
        res = await asyncio.to_thread(callable_obj, *args, **kwargs)
        return True, res
    except AzureError as exc:
        logger.warning(
            "Azure SDK error calling %s: %s",
            getattr(callable_obj, "__name__", callable_obj),
            exc,
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
