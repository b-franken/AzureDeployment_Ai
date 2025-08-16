from collections.abc import Iterable
from typing import Any


class BicepWriter:
    def __init__(self) -> None:
        self._lines: list[str] = []

    def line(self, s: str) -> None:
        self._lines.append(s)

    def extend(self, lines: Iterable[str]) -> None:
        self._lines.extend(lines)

    def render(self) -> str:
        return "\n".join(self._lines) + "\n"

    def obj(self, d: dict[str, Any]) -> str:
        items = ", ".join(f"{k}: {self._fmt(v)}" for k, v in d.items())
        return "{ " + items + " }"

    def arr(self, a: list[Any]) -> str:
        inner = ", ".join(self._fmt(v) for v in a)
        return "[ " + inner + " ]"

    def _fmt(self, v: Any) -> str:
        if isinstance(v, str):
            return "'" + v.replace("'", "\\'") + "'"
        if isinstance(v, bool):
            return "true" if v else "false"
        if v is None:
            return "null"
        if isinstance(v, int | float):
            return str(v)
        if isinstance(v, dict):
            return self.obj(v)
        if isinstance(v, list):
            return self.arr(v)
        return "'" + str(v).replace("'", "\\'") + "'"
