from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable

from app.core.logging import get_logger

logger = get_logger(__name__)


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
    logger.debug("Starting retry operation", attempts=attempts, backoff_seconds=backoff_seconds)
    if attempts < 1:
        logger.error("Invalid attempts parameter", attempts=attempts)
        raise ValueError("attempts must be >= 1")
    if backoff_seconds < 0:
        logger.error("Invalid backoff_seconds parameter", backoff_seconds=backoff_seconds)
        raise ValueError("backoff_seconds must be >= 0")

    if attempts == 1:
        logger.debug("Single attempt, executing function directly")
        return await fn()

    for attempt in range(attempts - 1):
        try:
            logger.debug("Executing function attempt", attempt=attempt + 1, total_attempts=attempts)
            return await fn()
        except asyncio.CancelledError:
            logger.warning("Operation cancelled during retry", attempt=attempt + 1)
            raise
        except BaseException as e:
            logger.warning(
                "Function attempt failed, retrying",
                attempt=attempt + 1,
                error=str(e),
                error_type=type(e).__name__,
            )
            if backoff_seconds > 0:
                jitter = random.uniform(0.0, backoff_seconds / 2)
                sleep_time = backoff_seconds + jitter
                logger.debug("Backing off before retry", sleep_time=sleep_time)
                await asyncio.sleep(sleep_time)
            else:
                await asyncio.sleep(0)

    logger.debug("Final attempt", attempt=attempts)
    return await fn()
