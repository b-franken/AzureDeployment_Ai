from __future__ import annotations

from collections.abc import Iterable

try:
    import tiktoken
except Exception:  # noqa: BLE001
    tiktoken = None  # type: ignore[assignment]


def estimate_tokens(texts: Iterable[str]) -> int:
    if tiktoken is None:
        return sum(max(1, len(t) // 4) for t in texts)
    enc = tiktoken.get_encoding("cl100k_base")
    return sum(len(enc.encode(t)) for t in texts)
