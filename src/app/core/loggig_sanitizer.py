from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

_SIMPLE_TYPES = (type(None), bool, int, float, str, bytes)


def _is_simple(value: Any) -> bool:
    if isinstance(value, _SIMPLE_TYPES):
        return True
    if isinstance(value, Mapping):
        return all(isinstance(k, str) and _is_simple(v) for k, v in value.items())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return all(_is_simple(v) for v in value)
    return False


def _coerce(value: Any) -> Any:
    if _is_simple(value):
        return value
    try:
        return str(value)
    except Exception:
        return repr(value)


def install_log_record_sanitizer() -> None:
    """
    Strip private / problematic attributes (e.g. _logger) and coerce values
    so third-party exporters (OpenTelemetry) don't crash during serialization.
    """
    original_factory = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = original_factory(*args, **kwargs)  # type: ignore[misc]

        for key in list(record.__dict__.keys()):
            if key.startswith("_"):
                del record.__dict__[key]

        for key, value in list(record.__dict__.items()):
            if key == "args":
                continue
            record.__dict__[key] = _coerce(value)

        return record

    logging.setLogRecordFactory(factory)
