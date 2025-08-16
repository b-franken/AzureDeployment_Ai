from collections.abc import Callable, Sequence
from typing import Any

from ..writer import BicepWriter


class SqlServerEmitter:
    def supports(self, rtype: str | None) -> bool:
        return rtype == "sql_server"

    def emit(
        self,
        idx: int,
        r: dict[str, Any],
        ctx: Any,
        w: BicepWriter,
        modref: Callable[[str], str],
    ) -> Sequence[str]:
        name = r["name"]
        version = r.get("version", "12.0")
        administrator_login = r.get("administrator_login", "")
        administrator_password = r.get("administrator_password", "")
        minimal_tls = r.get("minimal_tls_version", "1.2")
        public_network_access = r.get("public_network_access", "Disabled")
        props = ["    version: '" + version + "',"]
        if administrator_login:
            props.append("    administratorLogin: '" + administrator_login + "',")
        if administrator_password:
            props.append("    administratorLoginPassword: '" + administrator_password + "',")
        props.append("    minimalTlsVersion: '" + minimal_tls + "',")
        props.append("    publicNetworkAccess: '" + public_network_access + "'")
        return [
            "resource sqlsrv_" + str(idx) + " 'Microsoft.Sql/servers@2021-11-01-preview' = {",
            "  name: '" + name + "'",
            "  location: location",
            "  properties: {",
            *props,
            "  }",
            "  tags: tags",
            "}",
            "",
        ]


class SqlDatabaseEmitter:
    def supports(self, rtype: str | None) -> bool:
        return rtype == "sql_database"

    def emit(
        self,
        idx: int,
        r: dict[str, Any],
        ctx: Any,
        w: BicepWriter,
        modref: Callable[[str], str],
    ) -> Sequence[str]:
        server_name = r["server_name"]
        db_name = r["name"]
        sku_name = r.get("sku_name", "S0")
        max_size_gb = int(r.get("max_size_gb", 10))
        zone_redundant = bool(r.get("zone_redundant", False))
        return [
            "resource sqldb_"
            + str(idx)
            + " 'Microsoft.Sql/servers/databases@2021-11-01-preview' = {",
            "  name: '" + server_name + "/" + db_name + "'",
            "  location: location",
            "  sku: { name: '" + sku_name + "' }",
            "  properties: {",
            "    zoneRedundant: " + ("true" if zone_redundant else "false") + ",",
            "    maxSizeBytes: " + str(max_size_gb * 1024 * 1024 * 1024),
            "  }",
            "  tags: tags",
            "}",
            "",
        ]
