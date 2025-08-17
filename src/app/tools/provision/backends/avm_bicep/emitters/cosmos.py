from collections.abc import Callable, Sequence
from typing import Any

from ..writer import BicepWriter


class CosmosEmitter:
    def supports(self, rtype: str | None) -> bool:
        return rtype == "cosmos_account"

    def emit(
        self,
        idx: int,
        r: dict[str, Any],
        ctx: Any,
        w: BicepWriter,
        modref: Callable[[str], str],
    ) -> Sequence[str]:
        name = r["name"]
        kind = r.get("kind", "GlobalDocumentDB")
        consistency_level = r.get("consistency_level", "Session")
        enable_automatic_failover = bool(r.get("enable_automatic_failover", False))
        locations = r.get("locations", [{"location": "westeurope", "failover_priority": 0}])

        locations_bicep = []
        for loc in locations:
            locations_bicep.append(
                f"{{ locationName: '{loc['location']}', "
                f"failoverPriority: {loc['failover_priority']}, "
                "isZoneRedundant: true }}"
            )

        return [
            f"resource cosmos_{idx} 'Microsoft.DocumentDB/databaseAccounts@2023-11-15' = {{",
            f"  name: '{name}'",
            "  location: location",
            f"  kind: '{kind}'",
            "  properties: {",
            "    databaseAccountOfferType: 'Standard'",
            "    consistencyPolicy: {",
            f"      defaultConsistencyLevel: '{consistency_level}'",
            "    }",
            f"    locations: [{', '.join(locations_bicep)}]",
            f"    enableAutomaticFailover: {str(enable_automatic_failover).lower()}",
            "    enableMultipleWriteLocations: false",
            "    isVirtualNetworkFilterEnabled: false",
            "    virtualNetworkRules: []",
            "    disableKeyBasedMetadataWriteAccess: false",
            "    enableFreeTier: false",
            "    enableAnalyticalStorage: false",
            "    createMode: 'Default'",
            "    backupPolicy: {",
            "      type: 'Periodic'",
            "      periodicModeProperties: {",
            "        backupIntervalInMinutes: 240",
            "        backupRetentionIntervalInHours: 8",
            "      }",
            "    }",
            "  }",
            "  tags: tags",
            "}",
            "",
        ]
