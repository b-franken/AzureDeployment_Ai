from collections.abc import Callable, Sequence
from typing import Any

from ..writer import BicepWriter


class ResourceGroupEmitter:
    def supports(self, rtype: str | None) -> bool:
        return rtype == "resource_group"

    def emit(
        self,
        idx: int,
        r: dict[str, Any],
        ctx: Any,
        w: BicepWriter,
        modref: Callable[[str], str],
    ) -> Sequence[str]:
        mod = modref("resource/resource-group")
        name = r["name"]
        location = r.get("location", "location")

        return [
            f"module rg_{idx} '{mod}' = {{",
            f"  name: 'rg_{idx}'",
            "  scope: subscription()",
            "  params: {",
            f"    name: '{name}'",
            f"    location: {location}",
            "    tags: tags",
            "  }",
            "}",
            "",
        ]
