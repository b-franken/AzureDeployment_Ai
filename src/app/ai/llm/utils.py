from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable


async def retry_async[T](
    fn: Callable[[], Awaitable[T]],
    attempts: int,
    backoff_seconds: float,
) -> T:
    """
    Retry an async operation up to attempts times with jittered backoff.

    Args:
        fn: Zero-arg async function to execute.
        attempts: Total attempts, must be >= 1.
        backoff_seconds: Base backoff in seconds, must be >= 0.

    Returns:
        The awaited result of fn.

    Raises:
        The last exception raised by fn if all attempts fail.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    if backoff_seconds < 0:
        raise ValueError("backoff_seconds must be >= 0")

    if attempts == 1:
        return await fn()

    for _ in range(attempts - 1):
        try:
            return await fn()
        except asyncio.CancelledError:
            raise
        except BaseException:
            if backoff_seconds > 0:
                jitter = random.uniform(0.0, backoff_seconds / 2)
                await asyncio.sleep(backoff_seconds + jitter)
            else:
                await asyncio.sleep(0)

    return await fn()
