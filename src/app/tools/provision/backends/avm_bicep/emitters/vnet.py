from collections.abc import Callable, Sequence
from typing import Any

from ..writer import BicepWriter


class VnetEmitter:
    def supports(self, rtype: str | None) -> bool:
        return rtype == "vnet"

    def emit(
        self,
        idx: int,
        r: dict[str, Any],
        ctx: Any,
        w: BicepWriter,
        modref: Callable[[str], str],
    ) -> Sequence[str]:
        mod = modref("network/virtual-network")
        name = r["name"]
        addr = r.get("address_prefixes") or r.get("addressPrefixes") or ["10.10.0.0/16"]
        subnets = r.get("subnets") or []
        subs = []
        for s in subnets:
            subs.append(
                {
                    "name": s["name"],
                    "addressPrefix": s.get("addressPrefix")
                    or s.get("address_prefix")
                    or "10.10.1.0/24",
                    "privateEndpointNetworkPolicies": s.get(
                        "privateEndpointNetworkPolicies", "Disabled"
                    ),
                    "privateLinkServiceNetworkPolicies": s.get(
                        "privateLinkServiceNetworkPolicies", "Enabled"
                    ),
                }
            )
        return [
            "module vnet_" + str(idx) + " '" + mod + "' = {",
            "  name: 'vnet_" + str(idx) + "'",
            "  params: {",
            "    name: '" + name + "'",
            "    location: location",
            "    addressPrefixes: " + w.arr(addr),
            "    subnets: " + w.arr(subs),
            "    tags: tags",
            "  }",
            "}",
            "",
        ]
