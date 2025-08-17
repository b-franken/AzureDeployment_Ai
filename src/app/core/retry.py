from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

from tenacity import (
    RetryCallState,
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")

RETRIABLE_STATUS = {429, 500, 502, 503, 504}


def _status_code(e: BaseException) -> int | None:
    """Extract an HTTP status code from common exception shapes, or None."""
    status = getattr(e, "status_code", None)
    if status is not None:
        try:
            return int(status)
        except Exception:
            return None
    resp = getattr(e, "response", None)
    return getattr(resp, "status_code", None)


TRANSIENT_PREDICATE = retry_if_exception(
    lambda e: (
        isinstance(e, TimeoutError | ConnectionError)
        or type(e).__name__ in {"ReadTimeout", "ConnectTimeout", "HTTPStatusError"}
        or _status_code(e) in RETRIABLE_STATUS
    )
)


def _raise_outcome(state: RetryCallState) -> Any:
    """Tenacity callback used when retries are exhausted. Re-raise the original exception."""
    outcome = state.outcome
    if outcome is not None:
        exc = outcome.exception()
        if isinstance(exc, BaseException):
            raise exc
    raise RuntimeError("Retry failed without an exception outcome")


def common_retry(
    max_attempts: int = 6, max_wait: int = 60
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    return retry(
        reraise=True,
        stop=stop_after_attempt(max_attempts),
        wait=wait_random_exponential(multiplier=1, max=max_wait),
        retry=TRANSIENT_PREDICATE,
        before_sleep=before_sleep_log(logger, logging.WARNING),
        retry_error_callback=_raise_outcome,
    )
