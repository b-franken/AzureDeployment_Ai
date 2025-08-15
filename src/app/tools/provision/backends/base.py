from abc import ABC, abstractmethod
from typing import Any


class Backend(ABC):
    @abstractmethod
    async def plan(self, spec: dict[str, Any]) -> tuple[bool, str]:
        """Create a plan for provisioning resources.
        Returns (ok, plan_text)."""
        ...

    @abstractmethod
    async def apply(self, spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        """Execute the plan and return (ok, outputs_dict)."""
        ...
