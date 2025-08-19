from __future__ import annotations

import logging
from typing import Any

_installed = False

_PRIMITIVES = (type(None), bool, int, float, str, bytes)
_STANDARD_ATTRS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process",
}

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

class SanitizeRecordFilter(logging.Filter):
    """
    Drop private attrs (like '_logger') and stringify non-primitive extras,
    but NEVER touch 'msg' or 'args' so stdlib formatting stays intact.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        for key in [k for k in list(record.__dict__.keys()) if k.startswith("_")]:
            record.__dict__.pop(key, None)


        for key, value in list(record.__dict__.items()):
            if key in ("msg", "args", "exc_info") or key in _STANDARD_ATTRS:
                continue
            if not _is_safe(value):
                try:
                    record.__dict__[key] = str(value)
                except Exception:
                    record.__dict__.pop(key, None)
        return True

def install_log_record_sanitizer() -> None:
    """
    Install a root-logger filter that sanitizes every LogRecord before any handler sees it.
    Idempotent.
    """
    global _installed
    if _installed:
        return
    root = logging.getLogger()
    root.addFilter(SanitizeRecordFilter())
    _installed = True
