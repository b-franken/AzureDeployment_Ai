from __future__ import annotations

import abc
from typing import Any, TypedDict


class ToolResult(TypedDict, total=False):
    ok: bool
    summary: str
    output: str
    artifact_path: str | None


class Tool(abc.ABC):
    """Base class for all tools with proper type annotations."""

    name: str
    description: str
    schema: dict[str, Any]

    @abc.abstractmethod
    async def run(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with given parameters."""
        ...
