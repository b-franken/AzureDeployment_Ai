from collections.abc import Callable, Sequence
from typing import Any

from ..writer import BicepWriter


class ServiceBusEmitter:
    def supports(self, rtype: str | None) -> bool:
        return rtype == "service_bus"

    def emit(
        self,
        idx: int,
        r: dict[str, Any],
        ctx: Any,
        w: BicepWriter,
        modref: Callable[[str], str],
    ) -> Sequence[str]:
        name = r["name"]
        sku = r.get("sku", "Standard")
        zones = bool(r.get("zone_redundant", False))
        return [
            "resource sb_" + str(idx) + " 'Microsoft.ServiceBus/namespaces@2021-11-01' = {",
            "  name: '" + name + "'",
            "  location: location",
            "  sku: { name: '" + sku + "' }",
            "  properties: { zoneRedundant: " + ("true" if zones else "false") + " }",
            "  tags: tags",
            "}",
            "",
        ]
