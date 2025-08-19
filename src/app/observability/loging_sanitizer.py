from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any


def _is_allowed_value(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str | int | float | bool | bytes):
        return True
    if isinstance(v, Mapping):
        return all(isinstance(k, str) and _is_allowed_value(val) for k, val in v.items())
    if isinstance(v, Sequence) and not isinstance(v, str | bytes | bytearray):
        return all(isinstance(x, str | int | float | bool | bytes) for x in v)
    return False


def _sanitize_record(record: logging.LogRecord) -> None:
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
    }
    to_delete: list[str] = []
    for key, value in list(record.__dict__.items()):
        if key == "exc_info":
            if value and value is not True and not isinstance(value, tuple):
                record.__dict__[key] = True
            continue
        if key in std:
            continue
        if key.startswith("_"):
            to_delete.append(key)
            continue
        if not _is_allowed_value(value):
            record.__dict__[key] = str(value)
    for key in to_delete:
        del record.__dict__[key]


def install_log_record_sanitizer() -> None:
    orig = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        rec = orig(*args, **kwargs)
        _sanitize_record(rec)
        return rec

    logging.setLogRecordFactory(factory)
