from collections.abc import Callable, Sequence
from typing import Any

from ..writer import BicepWriter


class KeyVaultEmitter:
    def supports(self, rtype: str | None) -> bool:
        return rtype == "key_vault"

    def emit(
        self,
        idx: int,
        r: dict[str, Any],
        ctx: Any,
        w: BicepWriter,
        modref: Callable[[str], str],
    ) -> Sequence[str]:
        mod = modref("key-vault/vault")
        name = r["name"]
        enable_rbac = bool(r.get("enable_rbac", True))
        purge = bool(r.get("purge_protection", True))
        sdr = int(r.get("soft_delete_retention_in_days", 90))
        return [
            "module kv_" + str(idx) + " '" + mod + "' = {",
            "  name: 'kv_" + str(idx) + "'",
            "  params: {",
            "    name: '" + name + "'",
            "    location: location",
            "    enableRbacAuthorization: " + ("true" if enable_rbac else "false"),
            "    enablePurgeProtection: " + ("true" if purge else "false"),
            "    softDeleteRetentionInDays: " + str(sdr),
            "    tags: tags",
            "  }",
            "}",
            "",
        ]
