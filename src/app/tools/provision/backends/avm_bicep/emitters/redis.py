from collections.abc import Callable, Sequence
from typing import Any

from ..writer import BicepWriter


class RedisEmitter:
    def supports(self, rtype: str | None) -> bool:
        return rtype == "redis"

    def emit(
        self,
        idx: int,
        r: dict[str, Any],
        ctx: Any,
        w: BicepWriter,
        modref: Callable[[str], str],
    ) -> Sequence[str]:
        name = r["name"]
        sku_name = r.get("sku_name", "Premium")
        capacity = int(r.get("capacity", 1))
        enable_non_ssl = bool(r.get("enable_non_ssl_port", False))
        minimum_tls = r.get("minimum_tls_version", "1.2")
        return [
            "resource redis_" + str(idx) + " 'Microsoft.Cache/Redis@2023-08-01' = {",
            "  name: '" + name + "'",
            "  location: location",
            "  properties: {",
            "    enableNonSslPort: " + ("true" if enable_non_ssl else "false") + ",",
            "    minimumTlsVersion: '" + minimum_tls + "',",
            "    sku: { name: '" + sku_name + "', family: 'P', capacity: " + str(capacity) + " }",
            "  }",
            "  tags: tags",
            "}",
            "",
        ]
