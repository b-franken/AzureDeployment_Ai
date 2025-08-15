from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any


async def safe_get(callable_obj: Callable[..., Any], *args: Any, **kwargs: Any) -> tuple[bool, Any]:
    try:
        res = await asyncio.to_thread(callable_obj, *args, **kwargs)
        return True, res
    except Exception:
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
