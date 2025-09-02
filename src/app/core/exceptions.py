from __future__ import annotations

import asyncio
import inspect
import random
import sys
import traceback
import warnings
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
from typing import Any, ParamSpec, TypeVar, cast

import structlog
from prometheus_client import Counter, Gauge, Histogram

P = ParamSpec("P")
R = TypeVar("R")
ExceptionHandler = Callable[[Exception], Any]

error_counter = Counter(
    "app_errors_total",
    "Total number of errors",
    ["error_type", "severity", "module", "handled"],
)

error_duration = Histogram(
    "app_error_recovery_duration_seconds",
    "Time taken to recover from errors",
    ["error_type"],
)

active_errors = Gauge(
    "app_active_errors",
    "Currently active unresolved errors",
    ["error_type"],
)


class ErrorSeverity(Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
    FATAL = "fatal"


class ErrorCategory(Enum):
    VALIDATION = "validation"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    NETWORK = "network"
    DATABASE = "database"
    EXTERNAL_SERVICE = "external_service"
    RESOURCE_LIMIT = "resource_limit"
    CONFIGURATION = "configuration"
    BUSINESS_LOGIC = "business_logic"
    SYSTEM = "system"
    UNKNOWN = "unknown"


@dataclass
class ErrorContext:
    error_id: str
    timestamp: datetime
    error_type: str
    error_message: str
    severity: ErrorSeverity
    category: ErrorCategory
    module: str
    function: str
    line_number: int
    user_id: str | None = None
    request_id: str | None = None
    correlation_id: str | None = None
    stack_trace: str | None = None
    local_variables: dict[str, Any] = field(default_factory=dict)
    request_data: dict[str, Any] = field(default_factory=dict)
    system_state: dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    max_retries: int = 3
    recovery_attempted: bool = False
    recovery_successful: bool = False
    recovery_strategy: str | None = None
    affected_users: list[str] = field(default_factory=list)
    affected_resources: list[str] = field(default_factory=list)
    estimated_impact: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_id": self.error_id,
            "timestamp": self.timestamp.isoformat(),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "severity": self.severity.value,
            "category": self.category.value,
            "module": self.module,
            "function": self.function,
            "line_number": self.line_number,
            "user_id": self.user_id,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "stack_trace": self.stack_trace,
            "retry_count": self.retry_count,
            "recovery_attempted": self.recovery_attempted,
            "recovery_successful": self.recovery_successful,
        }


class BaseApplicationException(Exception):
    severity: ErrorSeverity = ErrorSeverity.ERROR
    category: ErrorCategory = ErrorCategory.UNKNOWN
    retryable: bool = False
    user_message: str | None = None

    def __init__(
        self,
        message: str,
        *,
        severity: ErrorSeverity | None = None,
        category: ErrorCategory | None = None,
        retryable: bool | None = None,
        user_message: str | None = None,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.severity = severity or self.severity
        self.category = category or self.category
        self.retryable = retryable if retryable is not None else self.retryable
        self.user_message = user_message or self.user_message or message
        self.details = details or {}
        self.cause = cause
        self.timestamp = datetime.utcnow()
        self.error_id = self._generate_error_id()

    def _generate_error_id(self) -> str:
        import uuid

        return f"ERR-{uuid.uuid4().hex[:12].upper()}"

    def get_context(self) -> ErrorContext:
        frame = sys.exc_info()[2]
        tb = traceback.extract_tb(frame) if frame else []
        location = tb[-1] if tb else None
        return ErrorContext(
            error_id=self.error_id,
            timestamp=self.timestamp,
            error_type=self.__class__.__name__,
            error_message=self.message,
            severity=self.severity,
            category=self.category,
            module=location.filename if location else "unknown",
            function=location.name if location else "unknown",
            line_number=0 if not location or location.lineno is None else location.lineno,
            stack_trace=traceback.format_exc() if frame else None,
        )


class ValidationException(BaseApplicationException):
    severity = ErrorSeverity.WARNING
    category = ErrorCategory.VALIDATION
    user_message = "The provided data is invalid"


class AuthenticationException(BaseApplicationException):
    severity = ErrorSeverity.WARNING
    category = ErrorCategory.AUTHENTICATION
    user_message = "Authentication failed"


class AuthorizationException(BaseApplicationException):
    severity = ErrorSeverity.WARNING
    category = ErrorCategory.AUTHORIZATION
    user_message = "You do not have permission to perform this action"


class ResourceNotFoundException(BaseApplicationException):
    severity = ErrorSeverity.WARNING
    category = ErrorCategory.BUSINESS_LOGIC
    user_message = "The requested resource was not found"


class RateLimitException(BaseApplicationException):
    severity = ErrorSeverity.WARNING
    category = ErrorCategory.RESOURCE_LIMIT
    retryable = True
    user_message = "Too many requests. Please try again later"


class ExternalServiceException(BaseApplicationException):
    severity = ErrorSeverity.ERROR
    category = ErrorCategory.EXTERNAL_SERVICE
    retryable = True
    user_message = "An external service is temporarily unavailable"


class DatabaseException(BaseApplicationException):
    severity = ErrorSeverity.ERROR
    category = ErrorCategory.DATABASE
    retryable = True


class ConfigurationException(BaseApplicationException):
    severity = ErrorSeverity.CRITICAL
    category = ErrorCategory.CONFIGURATION


class ConfigurationError(ConfigurationException):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field


class CircuitBreakerException(BaseApplicationException):
    severity = ErrorSeverity.ERROR
    category = ErrorCategory.SYSTEM
    retryable = False
    user_message = "Service temporarily unavailable due to high error rate"


class ErrorRecoveryStrategy:
    async def can_recover(self, error: BaseApplicationException) -> bool:
        return error.retryable

    async def recover(
        self,
        error: BaseApplicationException,
        context: ErrorContext,
        func: Callable[..., Any] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        raise NotImplementedError


class RetryStrategy(ErrorRecoveryStrategy):
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base

    async def can_recover(self, error: BaseApplicationException) -> bool:
        return error.retryable

    async def recover(
        self,
        error: BaseApplicationException,
        context: ErrorContext,
        func: Callable[..., Any] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if func is None:
            raise error
        for attempt in range(self.max_retries):
            delay = min(self.base_delay * (self.exponential_base**attempt), self.max_delay)
            await asyncio.sleep(delay)
            try:
                result = await func(*args, **kwargs)
                context.recovery_successful = True
                return result
            except Exception:
                context.retry_count = attempt + 1
                if attempt == self.max_retries - 1:
                    raise
        raise error


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: type[Exception] = Exception,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.failure_count = 0
        self.last_failure_time: datetime | None = None
        self.state = "closed"

    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if self.state == "open":
            if self._should_attempt_reset():
                self.state = "half-open"
            else:
                raise CircuitBreakerException("Circuit breaker is open")
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception:
            self._on_failure()
            raise

    def _should_attempt_reset(self) -> bool:
        if self.last_failure_time is None:
            return True
        time_since_failure = (datetime.utcnow() - self.last_failure_time).total_seconds()
        return time_since_failure >= self.recovery_timeout

    def _on_success(self) -> None:
        self.failure_count = 0
        self.state = "closed"

    def _on_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()
        if self.failure_count >= self.failure_threshold:
            self.state = "open"


class ErrorHandler:
    def __init__(self) -> None:
        self.logger = structlog.get_logger()
        self.handlers: dict[type[Exception], list[ExceptionHandler]] = defaultdict(list)
        self.recovery_strategies: dict[ErrorCategory, ErrorRecoveryStrategy] = {}
        self.circuit_breakers: dict[str, CircuitBreaker] = {}
        self.error_history: list[ErrorContext] = []
        self.max_history_size = 1000
        self._setup_default_strategies()

    def _setup_default_strategies(self) -> None:
        self.recovery_strategies[ErrorCategory.NETWORK] = RetryStrategy()
        self.recovery_strategies[ErrorCategory.DATABASE] = RetryStrategy(max_retries=5)
        self.recovery_strategies[ErrorCategory.EXTERNAL_SERVICE] = RetryStrategy()

    def register_handler(self, exception_type: type[Exception], handler: ExceptionHandler) -> None:
        self.handlers[exception_type].append(handler)

    def register_recovery_strategy(
        self,
        category: ErrorCategory,
        strategy: ErrorRecoveryStrategy,
    ) -> None:
        self.recovery_strategies[category] = strategy

    def get_circuit(self, key: str, **kwargs: Any) -> CircuitBreaker:
        cb = self.circuit_breakers.get(key)
        if cb is None:
            cb = CircuitBreaker(**kwargs)
            self.circuit_breakers[key] = cb
        return cb

    async def handle_error(
        self,
        error: Exception,
        context: dict[str, Any] | None = None,
        recover: bool = True,
    ) -> Any | None:
        import time

        start = time.monotonic()
        metrics_updated = False
        error_type_for_metrics: str | None = None

        try:
            if isinstance(error, BaseApplicationException):
                error_context = error.get_context()
            else:
                error_context = self._create_error_context(error)

            if context:
                error_context.request_data.update(context)

            self._log_error(error_context)
            self._update_metrics(error_context)
            metrics_updated = True
            error_type_for_metrics = error_context.error_type
            self._store_error(error_context)

            for handler in self.handlers.get(type(error), []):
                try:
                    res = handler(error)
                    if inspect.isawaitable(res):
                        await res
                except Exception as e:
                    self.logger.error("Error handler failed", error=str(e))

            if recover and isinstance(error, BaseApplicationException):
                strategy = self.recovery_strategies.get(error.category)
                if strategy and await strategy.can_recover(error):
                    try:
                        error_context.recovery_attempted = True
                        raise error
                    except Exception as e:
                        self.logger.error("Recovery failed", error=str(e))

            raise error
        finally:
            if metrics_updated and error_type_for_metrics:
                duration = time.monotonic() - start
                error_duration.labels(error_type=error_type_for_metrics).observe(duration)
                active_errors.labels(error_type=error_type_for_metrics).dec()

    def _create_error_context(self, error: Exception) -> ErrorContext:
        import uuid

        frame = sys.exc_info()[2]
        tb = traceback.extract_tb(frame) if frame else []
        location = tb[-1] if tb else None
        return ErrorContext(
            error_id=f"ERR-{uuid.uuid4().hex[:12].upper()}",
            timestamp=datetime.utcnow(),
            error_type=type(error).__name__,
            error_message=str(error),
            severity=ErrorSeverity.ERROR,
            category=ErrorCategory.UNKNOWN,
            module=location.filename if location else "unknown",
            function=location.name if location else "unknown",
            line_number=0 if not location or location.lineno is None else location.lineno,
            stack_trace=traceback.format_exc() if frame else None,
        )

    def _log_error(self, context: ErrorContext) -> None:
        self.logger.error("Error occurred", **context.to_dict())

    def _update_metrics(self, context: ErrorContext) -> None:
        error_counter.labels(
            error_type=context.error_type,
            severity=context.severity.value,
            module=context.module,
            handled=str(context.recovery_successful),
        ).inc()
        active_errors.labels(error_type=context.error_type).inc()

    def _store_error(self, context: ErrorContext) -> None:
        self.error_history.append(context)
        if len(self.error_history) > self.max_history_size:
            self.error_history = self.error_history[-self.max_history_size :]

    def get_error_summary(self, time_window: timedelta | None = None) -> dict[str, Any]:
        if time_window:
            cutoff = datetime.utcnow() - time_window
            errors = [e for e in self.error_history if e.timestamp > cutoff]
        else:
            errors = self.error_history

        by_severity: defaultdict[str, int] = defaultdict(int)
        by_category: defaultdict[str, int] = defaultdict(int)
        recovery_rate = 0

        for error in errors:
            by_severity[error.severity.value] += 1
            by_category[error.category.value] += 1
            if error.recovery_attempted and error.recovery_successful:
                recovery_rate += 1

        return {
            "total_errors": len(errors),
            "by_severity": dict(by_severity),
            "by_category": dict(by_category),
            "recovery_rate": recovery_rate / len(errors) if errors else 0,
            "time_window": str(time_window) if time_window else "all",
        }


def handle_errors(
    *,
    recover: bool = True,
    default_return: Any = None,
    log_level: ErrorSeverity = ErrorSeverity.ERROR,
) -> Callable[[Callable[P, Any]], Callable[P, Any]]:
    def decorator(func: Callable[P, Any]) -> Callable[P, Any]:
        @wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            handler = ErrorHandler()
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                try:
                    return await handler.handle_error(e, recover=recover)
                except Exception:
                    if default_return is not None:
                        log = structlog.get_logger()
                        if log_level == ErrorSeverity.DEBUG:
                            log.debug("Handled error with default return", error=str(e))
                        elif log_level == ErrorSeverity.INFO:
                            log.info("Handled error with default return", error=str(e))
                        elif log_level == ErrorSeverity.WARNING:
                            log.warning("Handled error with default return", error=str(e))
                        elif log_level in (ErrorSeverity.CRITICAL, ErrorSeverity.FATAL):
                            log.critical("Handled error with default return", error=str(e))
                        else:
                            log.error("Handled error with default return", error=str(e))
                        return default_return
                    raise

        @wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            handler = ErrorHandler()
            try:
                return func(*args, **kwargs)
            except Exception as e:
                try:
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = None
                    if loop and loop.is_running():

                        async def run_handler(exc: Exception = e) -> Any:
                            try:
                                return await handler.handle_error(exc, recover=recover)
                            except Exception:
                                if default_return is not None:
                                    log = structlog.get_logger()
                                    if log_level == ErrorSeverity.DEBUG:
                                        log.debug(
                                            "Handled error with default return", error=str(exc)
                                        )
                                    elif log_level == ErrorSeverity.INFO:
                                        log.info(
                                            "Handled error with default return", error=str(exc)
                                        )
                                    elif log_level == ErrorSeverity.WARNING:
                                        log.warning(
                                            "Handled error with default return", error=str(exc)
                                        )
                                    elif log_level in (ErrorSeverity.CRITICAL, ErrorSeverity.FATAL):
                                        log.critical(
                                            "Handled error with default return", error=str(exc)
                                        )
                                    else:
                                        log.error(
                                            "Handled error with default return", error=str(exc)
                                        )
                                    return default_return
                                raise

                        return loop.create_task(run_handler())
                    return asyncio.run(ErrorHandler().handle_error(e, recover=recover))
                except Exception:
                    if default_return is not None:
                        log = structlog.get_logger()
                        if log_level == ErrorSeverity.DEBUG:
                            log.debug("Handled error with default return", error=str(e))
                        elif log_level == ErrorSeverity.INFO:
                            log.info("Handled error with default return", error=str(e))
                        elif log_level == ErrorSeverity.WARNING:
                            log.warning("Handled error with default return", error=str(e))
                        elif log_level in (ErrorSeverity.CRITICAL, ErrorSeverity.FATAL):
                            log.critical("Handled error with default return", error=str(e))
                        else:
                            log.error("Handled error with default return", error=str(e))
                        return default_return
                    raise

        if asyncio.iscoroutinefunction(func):
            return cast("Callable[P, Any]", async_wrapper)
        return cast("Callable[P, Any]", sync_wrapper)

    return decorator


def retry_on_error(
    max_retries: int = 5,
    base_delay: float = 0.2,
    max_delay: float = 30.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    predicate: Callable[[BaseException], bool] | None = None,
    delay: float | None = None,
) -> Callable[[Callable[P, Any]], Callable[P, Any]]:
    if delay is not None:
        warnings.warn(
            "retry_on_error(delay=...) is deprecated. Use base_delay=...",
            DeprecationWarning,
            stacklevel=2,
        )
        base: float = delay
    else:
        base = base_delay

    def backoff(attempt: int) -> float:
        return float(min(max_delay, base * (2**attempt)) * random.uniform(0.5, 1.5))

    def decorator(func: Callable[P, Any]) -> Callable[P, Any]:
        @wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            last: BaseException | None = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    if predicate and not predicate(e):
                        raise
                    last = e
                    if attempt < max_retries - 1:
                        await asyncio.sleep(backoff(attempt))
            assert last is not None
            raise last

        @wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            import time

            last: BaseException | None = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if predicate and not predicate(e):
                        raise
                    last = e
                    if attempt < max_retries - 1:
                        time.sleep(backoff(attempt))
            assert last is not None
            raise last

        if asyncio.iscoroutinefunction(func):
            return cast("Callable[P, Any]", async_wrapper)
        return cast("Callable[P, Any]", sync_wrapper)

    return decorator


error_handler = ErrorHandler()
