from __future__ import annotations

import logging
import logging.handlers
import sys
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import structlog
from opentelemetry import trace
from structlog.contextvars import bind_contextvars, clear_contextvars, merge_contextvars
from structlog.stdlib import ProcessorFormatter

PreProcessor = Callable[
    [Any, str, MutableMapping[str, Any]],
    Mapping[str, Any] | str | bytes | bytearray | tuple[Any, ...],
]

_SIMPLE_TYPES = (type(None), bool, int, float, str, bytes)


def _is_simple(value: Any) -> bool:
    if isinstance(value, _SIMPLE_TYPES):
        return True
    if isinstance(value, Mapping):
        return all(isinstance(k, str) and _is_simple(v) for k, v in value.items())
    if isinstance(value, Sequence) and not isinstance(value, (str | bytes | bytearray)):
        return all(_is_simple(v) for v in value)
    return False


def _coerce(value: Any) -> Any:
    if _is_simple(value):
        return value
    if isinstance(value, Mapping):
        return {str(_coerce(k)): _coerce(v) for k, v in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str | bytes | bytearray)):
        return [_coerce(v) for v in value]
    try:
        return str(value)
    except Exception:
        return repr(value)


def install_log_record_sanitizer() -> None:
    std = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "asctime",
        "_FixedFindCallerLogger",
    }
    original_factory = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = original_factory(*args, **kwargs)  # type: ignore[misc]

        for key in list(record.__dict__.keys()):
            if key.startswith("_"):
                del record.__dict__[key]

        for key, value in list(record.__dict__.items()):
            if key == "exc_info":
                if value and value is not True and not isinstance(value, tuple):
                    record.__dict__[key] = True
                continue
            if key in std:
                continue
            record.__dict__[key] = _coerce(value)

        return record

    logging.setLogRecordFactory(factory)


class ContextFilter(logging.Filter):
    def __init__(self, context: dict[str, Any] | None = None):
        super().__init__()
        self.context = context or {}

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in self.context.items():
            setattr(record, key, value)
        return True


def _drop_private_keys(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> Mapping[str, Any]:
    return {k: v for k, v in event_dict.items() if not str(k).startswith("_")}


def _otel_enricher(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> Mapping[str, Any]:
    span = trace.get_current_span()
    ctx = span.get_span_context() if span else None
    if ctx and ctx.is_valid:
        event_dict["trace_id"] = f"{ctx.trace_id:032x}"
        event_dict["span_id"] = f"{ctx.span_id:016x}"
    return event_dict


class LoggerFactory:
    _instance: LoggerFactory | None = None
    _configured: bool = False

    def __new__(cls) -> LoggerFactory:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def configure(
        self,
        level: str = "INFO",
        fmt: str = "json",
        log_file: Path | str | None = None,
        max_bytes: int | None = None,
        retention: int = 30,
        rotate_when: str = "D",
        rotate_interval: int = 1,
        enable_console: bool = True,
        context: dict[str, Any] | None = None,
    ) -> None:
        if self._configured:
            return

        install_log_record_sanitizer()

        log_level = getattr(logging, level.upper(), logging.INFO)
        renderer = (
            structlog.processors.JSONRenderer()
            if fmt == "json"
            else structlog.dev.ConsoleRenderer()
        )
        pre_chain_raw = [
            merge_contextvars,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", key="@timestamp"),
        ]
        pre_chain: Sequence[PreProcessor] = cast(Sequence[PreProcessor], pre_chain_raw)

        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                merge_contextvars,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.processors.TimeStamper(fmt="iso", key="@timestamp"),
                _drop_private_keys,
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                _otel_enricher,
                ProcessorFormatter.wrap_for_formatter,
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

        root_logger = logging.getLogger()
        root_logger.setLevel(log_level)
        root_logger.handlers.clear()

        formatter = ProcessorFormatter(processor=renderer, foreign_pre_chain=pre_chain)

        if enable_console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            console_handler.addFilter(ContextFilter(context))
            root_logger.addHandler(console_handler)

        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            if max_bytes and max_bytes > 0:
                file_handler: logging.handlers.BaseRotatingHandler = (
                    logging.handlers.RotatingFileHandler(
                        str(log_path),
                        maxBytes=max_bytes,
                        backupCount=retention,
                        encoding="utf-8",
                    )
                )
            else:
                file_handler = logging.handlers.TimedRotatingFileHandler(
                    str(log_path),
                    when=rotate_when,
                    interval=rotate_interval,
                    backupCount=retention,
                    utc=True,
                    encoding="utf-8",
                )
            file_handler.setFormatter(formatter)
            file_handler.addFilter(ContextFilter(context))
            root_logger.addHandler(file_handler)

        if context:
            bind_contextvars(**context)

        logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(
            logging.WARNING
        )
        logging.getLogger("azure.monitor.opentelemetry").setLevel(logging.WARNING)

        self._configured = True

    def get_logger(self, name: str) -> structlog.BoundLogger:
        if not self._configured:
            self.configure()
        return structlog.get_logger(name)

    def add_context(self, **kwargs: Any) -> None:
        bind_contextvars(**kwargs)

    def clear_context(self) -> None:
        clear_contextvars()


class LoggingMiddleware:
    def __init__(self, logger: structlog.BoundLogger):
        self.logger = logger

    async def log_request(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        body: Any = None,
        **kwargs: Any,
    ) -> None:
        self.logger.info(
            "Request received",
            method=method,
            path=path,
            headers=self._sanitize_headers(headers),
            has_body=body is not None,
            **kwargs,
        )

    async def log_response(
        self,
        status: int,
        headers: dict[str, str],
        duration_ms: float,
        **kwargs: Any,
    ) -> None:
        level = "info" if 200 <= status < 400 else "warning" if status < 500 else "error"
        getattr(self.logger, level)(
            "Response sent",
            status=status,
            headers=self._sanitize_headers(headers),
            duration_ms=duration_ms,
            **kwargs,
        )

    async def log_error(
        self,
        error: Exception,
        context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.logger.error(
            "Request failed",
            error_type=type(error).__name__,
            error_message=str(error),
            context=context,
            exc_info=True,
            **kwargs,
        )

    def _sanitize_headers(self, headers: dict[str, str]) -> dict[str, str]:
        sensitive_headers = {
            "authorization",
            "proxy-authorization",
            "cookie",
            "set-cookie",
            "x-api-key",
            "x-auth-token",
            "x-forwarded-for",
            "x-amzn-trace-id",
            "x-ms-client-principal",
            "x-azure-socketip",
        }
        sanitized: dict[str, str] = {}
        for key, value in headers.items():
            if key.lower() in sensitive_headers:
                sanitized[key] = "***REDACTED***"
            else:
                sanitized[key] = value
        return sanitized


class AuditLogger:
    def __init__(self, logger: structlog.BoundLogger):
        self.logger = logger

    async def log_action(
        self,
        user_id: str,
        action: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        result: str = "success",
        details: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.logger.info(
            "Audit trail",
            audit=True,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            result=result,
            details=details,
            timestamp=datetime.utcnow().isoformat(),
            **kwargs,
        )

    async def log_security_event(
        self,
        event_type: str,
        severity: str,
        user_id: str | None = None,
        ip_address: str | None = None,
        details: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        level = "warning" if severity in ["low", "medium"] else "error"
        getattr(self.logger, level)(
            "Security event",
            security=True,
            event_type=event_type,
            severity=severity,
            user_id=user_id,
            ip_address=ip_address,
            details=details,
            timestamp=datetime.utcnow().isoformat(),
            **kwargs,
        )


_factory = LoggerFactory()


def configure_logging(
    level: str = "INFO",
    fmt: str = "json",
    log_file: Path | str | None = None,
    max_bytes: int | None = None,
    retention: int = 30,
    rotate_when: str = "D",
    rotate_interval: int = 1,
    enable_console: bool = True,
    context: dict[str, Any] | None = None,
) -> None:
    _factory.configure(
        level=level,
        fmt=fmt,
        log_file=log_file,
        max_bytes=max_bytes,
        retention=retention,
        rotate_when=rotate_when,
        rotate_interval=rotate_interval,
        enable_console=enable_console,
        context=context,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    return _factory.get_logger(name)


def add_context(**kwargs: Any) -> None:
    _factory.add_context(**kwargs)


def clear_context() -> None:
    _factory.clear_context()


__all__ = [
    "configure_logging",
    "get_logger",
    "add_context",
    "clear_context",
    "LoggerFactory",
    "LoggingMiddleware",
    "AuditLogger",
    "install_log_record_sanitizer",
]
