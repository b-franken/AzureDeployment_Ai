from collections.abc import Callable, Sequence
from typing import Any

from ..writer import BicepWriter


class StorageAccountEmitter:
    def supports(self, rtype: str | None) -> bool:
        return rtype == "storage_account"

    def emit(
        self,
        idx: int,
        r: dict[str, Any],
        ctx: Any,
        w: BicepWriter,
        modref: Callable[[str], str],
    ) -> Sequence[str]:
        mod = modref("storage/storage-account")
        name = r["name"]
        sku = r.get("sku", "Standard_LRS")
        public_access = r.get("public_network_access", "Disabled")
        kind = r.get("kind", "StorageV2")
        allow_blob_public_access = bool(r.get("allow_blob_public_access", False))
        min_tls = r.get("min_tls_version", "TLS1_2")
        return [
            "module sa_" + str(idx) + " '" + mod + "' = {",
            "  name: 'sa_" + str(idx) + "'",
            "  params: {",
            "    name: '" + name + "'",
            "    location: location",
            "    skuName: '" + sku + "'",
            "    kind: '" + kind + "'",
            "    publicNetworkAccess: '" + public_access + "'",
            "    allowBlobPublicAccess: " + ("true" if allow_blob_public_access else "false"),
            "    minimumTlsVersion: '" + min_tls + "'",
            "    tags: tags",
            "  }",
            "}",
            "",
        ]
