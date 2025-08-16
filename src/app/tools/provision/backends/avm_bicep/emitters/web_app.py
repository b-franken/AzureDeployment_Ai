from collections.abc import Callable, Sequence
from typing import Any

from ..writer import BicepWriter


class WebAppEmitter:
    def supports(self, rtype: str | None) -> bool:
        return rtype == "web_stack"

    def emit(
        self,
        idx: int,
        r: dict[str, Any],
        ctx: Any,
        w: BicepWriter,
        modref: Callable[[str], str],
    ) -> Sequence[str]:
        site_mod = modref("web/site")
        base = r["name"]
        plan = r.get("plan", {}) or {}
        site = r.get("site", {}) or {}
        slots = r.get("slots", []) or []
        plan_name = plan.get("name") or (base + "-plan")
        sku = plan.get("sku", "P1v3")
        linux = bool(plan.get("linux", True))
        zone_redundant = bool(plan.get("zone_redundant", False))
        worker_count = int(plan.get("capacity", 1))
        kind = site.get("kind", "app,linux" if linux else "app")
        https_only = bool(site.get("https_only", True))
        app_settings = site.get("app_settings", {}) or {}
        site_config = {
            "alwaysOn": bool(site.get("always_on", True)),
            "minTlsVersion": site.get("min_tls_version", "1.2"),
            "ftpsState": site.get("ftps_state", "Disabled"),
        }
        if site.get("health_check_path"):
            site_config["healthCheckPath"] = site["health_check_path"]
        lines = [
            "resource plan_" + str(idx) + " 'Microsoft.Web/serverfarms@2023-12-01' = {",
            "  name: '" + plan_name + "'",
            "  location: location",
            "  sku: { name: '" + sku + "' }",
            "  properties: {",
            "    reserved: " + ("true" if linux else "false"),
            "    targetWorkerCount: " + str(worker_count),
            "    zoneRedundant: " + ("true" if zone_redundant else "false"),
            "  }",
            "  tags: tags",
            "}",
            "",
            "module site_" + str(idx) + " '" + site_mod + "' = {",
            "  name: 'site_" + str(idx) + "'",
            "  params: {",
            "    name: '" + base + "-app'",
            "    location: location",
            "    kind: '" + kind + "'",
            "    serverFarmResourceId: plan_" + str(idx) + ".id",
            "    httpsOnly: " + ("true" if https_only else "false"),
            "    appSettingsKeyValuePairs: " + (w.obj(app_settings) if app_settings else "null"),
            "    managedIdentities: { systemAssigned: true }",
            "    siteConfig: " + w.obj(site_config),
            "    tags: tags",
            "  }",
            "}",
            "",
        ]
        for s_i, s in enumerate(slots, start=1):
            slot_name = s.get("name", "staging")
            slot_app_settings = s.get("app_settings", {}) or {}
            slot_config = {
                "alwaysOn": bool(s.get("always_on", True)),
                "minTlsVersion": s.get("min_tls_version", "1.2"),
            }
            if s.get("health_check_path"):
                slot_config["healthCheckPath"] = s["health_check_path"]
            lines.extend(
                [
                    "resource site_"
                    + str(idx)
                    + "_slot_"
                    + str(s_i)
                    + " 'Microsoft.Web/sites/slots@2023-12-01' = {",
                    "  name: '" + base + "-app/" + slot_name + "'",
                    "  location: location",
                    "  properties: {",
                    "    serverFarmId: plan_" + str(idx) + ".id",
                    "    httpsOnly: true",
                    "    siteConfig: " + w.obj(slot_config),
                    "  }",
                    "  tags: tags",
                    "}",
                    "",
                    "resource site_"
                    + str(idx)
                    + "_slot_"
                    + str(s_i)
                    + "_appsettings 'Microsoft.Web/sites/slots/config@2023-12-01' = {",
                    "  name: '" + base + "-app/" + slot_name + "/appsettings'",
                    "  properties: " + (w.obj(slot_app_settings) if slot_app_settings else "{  }"),
                    "  dependsOn: [ site_" + str(idx) + "_slot_" + str(s_i) + " ]",
                    "}",
                    "",
                ]
            )
        return lines
