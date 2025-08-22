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


def dumps(obj: Any) -> bytes:
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return bytes(obj)
    if msgspec is not None:
        return msgspec.json.encode(obj)
    if orjson is not None:
        return orjson.dumps(obj)
    import json

    return json.dumps(obj, separators=(",", ":")).encode()


def loads(data: bytes | bytearray | memoryview | None) -> Any:
    if data is None:
        return None
    b = bytes(data)
    if msgspec is not None:
        return msgspec.json.decode(b)
    if orjson is not None:
        return orjson.loads(b)
    import json

    return json.loads(b.decode())
