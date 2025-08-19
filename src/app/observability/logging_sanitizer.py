from __future__ import annotations

import logging
from typing import Any

_installed = False

_PRIMITIVES = (type(None), bool, int, float, str, bytes)


def _is_safe(value: Any) -> bool:
    if isinstance(value, _PRIMITIVES):
        return True
    if isinstance(value, (list, tuple)):
        try:
            return all(_is_safe(v) for v in value)
        except Exception:
            return False
    if isinstance(value, dict):
        try:
            return all(isinstance(k, str) and _is_safe(v) for k, v in value.items())
        except Exception:
            return False
    return False


def install_log_record_sanitizer() -> None:
    """
    Sanitize logging.LogRecord objects so OpenTelemetry's log exporter
    does not choke on non-primitive attributes like structlog internals.
    Idempotent.
    """
    global _installed
    if _installed:
        return

    base_factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):  # type: ignore[no-untyped-def]
        record = base_factory(*args, **kwargs)

        for key in list(record.__dict__.keys()):
            if key.startswith("_"):
                record.__dict__.pop(key, None)

        for key, value in list(record.__dict__.items()):
            if not _is_safe(value):
                try:
                    record.__dict__[key] = str(value)
                except Exception:
                    record.__dict__.pop(key, None)

        return record

    logging.setLogRecordFactory(record_factory)
    _installed = True
