from collections.abc import Callable, Sequence
from typing import Any

from app.core.logging import get_logger

from ..writer import BicepWriter

logger = get_logger(__name__)


class AksEmitter:
    def supports(self, rtype: str | None) -> bool:
        return rtype == "aks_cluster"

    def emit(
        self,
        idx: int,
        r: dict[str, Any],
        ctx: Any,
        w: BicepWriter,
        modref: Callable[[str], str],
    ) -> Sequence[str]:
        name = r["name"]
        logger.info("Emitting AKS cluster", name=name, idx=idx)
        dns_prefix = r.get("dns_prefix", name)
        node_pools = r.get("node_pools", [])
        network_profile = r.get("network_profile", {})
        addons = r.get("addons", {})
        logger.debug(
            "AKS configuration",
            node_pools_count=len(node_pools),
            has_network_profile=bool(network_profile),
            addons=list(addons.keys()),
        )

        lines = [
            f"resource aks_{idx} 'Microsoft.ContainerService/managedClusters@2023-10-01' = {{",
            f"  name: '{name}'",
            "  location: location",
            "  identity: {",
            "    type: 'SystemAssigned'",
            "  }",
            "  properties: {",
            "    kubernetesVersion: '1.28'",
            f"    dnsPrefix: '{dns_prefix}'",
            "    enableRBAC: true",
            f"    nodeResourceGroup: '{name}-nodes-rg'",
        ]

        if node_pools:
            logger.debug("Processing node pools", count=len(node_pools))
            lines.append("    agentPoolProfiles: [")
            for pool in node_pools:
                logger.debug(
                    "Processing node pool",
                    pool_name=pool.get("name"),
                    vm_size=pool.get("vm_size"),
                    count=pool.get("count"),
                )
                lines.extend(
                    [
                        "      {",
                        f"        name: '{pool['name']}'",
                        f"        count: {pool['count']}",
                        f"        vmSize: '{pool['vm_size']}'",
                        f"        mode: '{pool.get('mode', 'User')}'",
                        "        osType: 'Linux'",
                        "        type: 'VirtualMachineScaleSets'",
                        "        enableAutoScaling: true",
                        f"        minCount: {pool.get('min_count', 1)}",
                        f"        maxCount: {pool.get('max_count', pool['count'] * 2)}",
                        "      }",
                    ]
                )
            lines.append("    ]")

        if network_profile:
            lines.extend(
                [
                    "    networkProfile: {",
                    f"      networkPlugin: '{network_profile.get('network_plugin', 'azure')}'",
                    f"      networkPolicy: '{network_profile.get('network_policy', 'azure')}'",
                    f"      serviceCidr: '{network_profile.get('service_cidr', '10.0.0.0/16')}'",
                    f"      dnsServiceIP: '{network_profile.get('dns_service_ip', '10.0.0.10')}'",
                    "    }",
                ]
            )

        if addons:
            lines.append("    addonProfiles: {")
            if addons.get("azure_policy"):
                lines.extend(
                    [
                        "      azurepolicy: {",
                        "        enabled: true",
                        "      }",
                    ]
                )
            if addons.get("monitoring"):
                lines.extend(
                    [
                        "      omsagent: {",
                        "        enabled: true",
                        "        config: {",
                        "          logAnalyticsWorkspaceResourceID: logAnalyticsWorkspaceId",
                        "        }",
                        "      }",
                    ]
                )
            if addons.get("ingress"):
                lines.extend(
                    [
                        "      httpApplicationRouting: {",
                        "        enabled: true",
                        "      }",
                    ]
                )
            lines.append("    }")

        lines.extend(
            [
                "  }",
                "  tags: tags",
                "}",
                "",
            ]
        )

        logger.info("AKS cluster emission completed", name=name, lines_generated=len(lines))
        return lines
