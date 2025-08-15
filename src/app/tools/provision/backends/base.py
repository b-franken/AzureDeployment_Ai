from abc import ABC, abstractmethod
from typing import Any


class Backend(ABC):
    @abstractmethod
    async def plan(self, spec: dict[str, Any]) -> tuple[bool, str]:
        """Maak een plan voor het provisioneren van resources.
        Retourneert (ok, plan_text)."""
        ...

    @abstractmethod
    async def apply(self, spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        """Voert het plan uit en retourneert (ok, outputs_dict)."""
        ...
