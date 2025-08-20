from __future__ import annotations

from collections import deque
from collections.abc import Iterable


class ConversationMemory:
    def __init__(self, maxlen: int = 50) -> None:
        self._buf: deque[dict[str, str]] = deque(maxlen=maxlen)

    def add(self, role: str, content: str) -> None:
        self._buf.append({"role": role, "content": content})

    def messages(self) -> list[dict[str, str]]:
        return list(self._buf)

    def extend(self, items: Iterable[dict[str, str]]) -> None:
        self._buf.extend(items)
