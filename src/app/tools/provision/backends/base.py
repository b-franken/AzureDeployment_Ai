from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

PlanResult = tuple[bool, str]
ApplyResult = tuple[bool, dict[str, Any]]


class Backend(ABC):
    @abstractmethod
    async def plan(self, spec: dict[str, Any]) -> PlanResult: ...

    @abstractmethod
    async def apply(self, spec: dict[str, Any]) -> ApplyResult: ...
