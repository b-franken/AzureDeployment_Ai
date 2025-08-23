from __future__ import annotations

import importlib
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


def _optional_import(name: str) -> Any | None:
    try:
        return importlib.import_module(name)
    except Exception:
        return None


msgspec: Any | None = _optional_import("msgspec")
orjson: Any | None = _optional_import("orjson")


def _std_json_dumps(obj: Any) -> bytes:
    import json

    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode()


def _std_json_loads(b: bytes) -> Any:
    import json

    return json.loads(b.decode())


def dumps(obj: Any) -> bytes:
    if isinstance(obj, bytes | bytearray | memoryview):
        return bytes(obj)
    if msgspec is not None:
        try:
            return msgspec.json.encode(obj)
        except Exception as exc:
            logger.debug(
                "cache.serializers.msgspec_encode_failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
    if orjson is not None:
        try:
            return orjson.dumps(obj)
        except Exception as exc:
            logger.debug(
                "cache.serializers.orjson_dumps_failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
    return _std_json_dumps(obj)


def loads(data: bytes | bytearray | memoryview | None) -> Any:
    if data is None:
        return None
    b = bytes(data)
    if msgspec is not None:
        try:
            return msgspec.json.decode(b)
        except Exception as exc:
            logger.debug(
                "cache.serializers.msgspec_decode_failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
    if orjson is not None:
        try:
            return orjson.loads(b)
        except Exception as exc:
            logger.debug(
                "cache.serializers.orjson_loads_failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
    return _std_json_loads(b)
