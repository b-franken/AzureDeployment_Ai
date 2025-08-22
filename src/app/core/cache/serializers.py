from __future__ import annotations

from typing import Any

try:
    import msgspec  # type: ignore[import-not-found]
except Exception:  # noqa: BLE001
    msgspec = None

try:
    import orjson  # type: ignore[import-not-found]
except Exception:  # noqa: BLE001
    orjson = None


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
        except Exception:  # noqa: BLE001
            pass
    if orjson is not None:
        try:
            return orjson.dumps(obj)
        except Exception:  # noqa: BLE001
            pass
    return _std_json_dumps(obj)


def loads(data: bytes | bytearray | memoryview | None) -> Any:
    if data is None:
        return None
    b = bytes(data)
    if msgspec is not None:
        try:
            return msgspec.json.decode(b)
        except Exception:  # noqa: BLE001
            pass
    if orjson is not None:
        try:
            return orjson.loads(b)
        except Exception:  # noqa: BLE001
            pass
    return _std_json_loads(b)
