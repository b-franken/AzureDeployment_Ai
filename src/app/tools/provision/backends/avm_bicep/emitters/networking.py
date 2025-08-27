from collections.abc import Callable, Sequence
from typing import Any

from ..writer import BicepWriter


class PrivateDnsZoneEmitter:
    def supports(self, rtype: str | None) -> bool:
        return rtype == "private_dns_zone"

    def emit(
        self,
        idx: int,
        r: dict[str, Any],
        ctx: Any,
        w: BicepWriter,
        modref: Callable[[str], str],
    ) -> Sequence[str]:
        zone = r["name"]
        return [
            "resource pdns_" + str(idx) + " 'Microsoft.Network/privateDnsZones@2020-06-01' = {",
            "  name: '" + zone + "'",
            "  location: 'global'",
            "  tags: tags",
            "}",
            "",
        ]


class PrivateDnsLinkEmitter:
    def supports(self, rtype: str | None) -> bool:
        return rtype == "private_dns_link"

    def emit(
        self,
        idx: int,
        r: dict[str, Any],
        ctx: Any,
        w: BicepWriter,
        modref: Callable[[str], str],
    ) -> Sequence[str]:
        zone = r["zone_name"]
        vnet_id = r["vnet_resource_id"]
        link_name = r.get("link_name", "link-" + str(idx))
        registration = bool(r.get("registration_enabled", False))
        return [
            "resource pdnslink_"
            + str(idx)
            + " 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {",
            "  name: '" + zone + "/" + link_name + "'",
            "  location: 'global'",
            "  properties: {",
            "    virtualNetwork: { id: '" + vnet_id + "' },",
            "    registrationEnabled: " + ("true" if registration else "false"),
            "  }",
            "  dependsOn: [ pdns_" + str(r.get("depends_on_pdns_idx", idx)) + " ]",
            "}",
            "",
        ]


class PrivateEndpointEmitter:
    def supports(self, rtype: str | None) -> bool:
        return rtype == "private_endpoint"

    def emit(
        self,
        idx: int,
        r: dict[str, Any],
        ctx: Any,
        w: BicepWriter,
        modref: Callable[[str], str],
    ) -> Sequence[str]:
        name = r["name"]
        subnet_id = r["subnet_resource_id"]
        target_id = r["target_resource_id"]
        group_ids = r.get("group_ids", ["blob"])
        dns_zone_ids = r.get("private_dns_zone_ids", [])
        out = [
            "resource pe_" + str(idx) + " 'Microsoft.Network/privateEndpoints@2023-05-01' = {",
            "  name: '" + name + "'",
            "  location: location",
            "  properties: {",
            "    subnet: { id: '" + subnet_id + "' },",
            "    privateLinkServiceConnections: [",
            "      {",
            "        name: '" + name + "-pls',",
            "        properties: {",
            "          privateLinkServiceId: '" + target_id + "',",
            "          groupIds: " + w.arr(group_ids),
            "        }",
            "      }",
            "    ]",
            "  }",
            "}",
            "",
        ]
        if dns_zone_ids:
            lines = [
                "resource peg_"
                + str(idx)
                + " 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2020-03-01' = {",
                "  name: '" + name + "/default'",
                "  properties: {",
                "    privateDnsZoneConfigs: [",
            ]
            for i, zid in enumerate(dns_zone_ids, start=1):
                lines.extend(
                    [
                        "      { name: 'zone"
                        + str(i)
                        + "', properties: { privateDnsZoneId: '"
                        + zid
                        + "' } },",
                    ]
                )
            lines[-1] = lines[-1].removesuffix(",")
            lines.extend(
                [
                    "    ]",
                    "  }",
                    "  dependsOn: [ pe_" + str(idx) + " ]",
                    "}",
                    "",
                ]
            )
            out.extend(lines)
        return out
