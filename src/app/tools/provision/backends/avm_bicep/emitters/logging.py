from collections.abc import Callable, Sequence
from typing import Any

from ..writer import BicepWriter


class LogAnalyticsEmitter:
    def supports(self, rtype: str | None) -> bool:
        return rtype == "log_analytics"

    def emit(
        self,
        idx: int,
        r: dict[str, Any],
        ctx: Any,
        w: BicepWriter,
        modref: Callable[[str], str],
    ) -> Sequence[str]:
        name = r["name"]
        sku = r.get("sku", "PerGB2018")
        retention = int(r.get("retention_in_days", 30))
        daily_cap_gb = r.get("daily_cap_gb", None)
        lines = [
            "resource la_"
            + str(idx)
            + " 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {",
            "  name: '" + name + "'",
            "  location: location",
            "  sku: { name: '" + sku + "' }",
            "  retentionInDays: " + str(retention),
            "  tags: tags",
            "}",
            "",
        ]
        if daily_cap_gb is not None:
            lines.extend(
                [
                    "resource la_"
                    + str(idx)
                    + "_cap 'Microsoft.OperationalInsights/workspaces/dailyCaps@2020-08-01' = {",
                    "  name: '" + name + "/default'",
                    "  properties: { limitGB: "
                    + str(daily_cap_gb)
                    + ", warningThresholdPercentage: 80 }",
                    "  dependsOn: [ la_" + str(idx) + " ]",
                    "}",
                    "",
                ]
            )
        return lines


class AppInsightsEmitter:
    def supports(self, rtype: str | None) -> bool:
        return rtype == "app_insights"

    def emit(
        self,
        idx: int,
        r: dict[str, Any],
        ctx: Any,
        w: BicepWriter,
        modref: Callable[[str], str],
    ) -> Sequence[str]:
        name = r["name"]
        kind = r.get("kind", "web")
        app_type = r.get("application_type", "web")
        workspace_id = r.get("workspace_resource_id")
        props = {
            "Application_Type": app_type,
            "Flow_Type": "Bluefield",
            "IngestionMode": "ApplicationInsights",
        }
        if workspace_id:
            props["WorkspaceResourceId"] = workspace_id
        return [
            "resource ai_" + str(idx) + " 'Microsoft.Insights/components@2020-02-02' = {",
            "  name: '" + name + "'",
            "  location: location",
            "  kind: '" + kind + "'",
            "  properties: " + w.obj(props),
            "  tags: tags",
            "}",
            "",
        ]


class DiagnosticSettingsEmitter:
    def supports(self, rtype: str | None) -> bool:
        return rtype == "diagnostic_settings"

    def emit(
        self,
        idx: int,
        r: dict[str, Any],
        ctx: Any,
        w: BicepWriter,
        modref: Callable[[str], str],
    ) -> Sequence[str]:
        name = r.get("name", "diag-" + str(idx))
        target_id = r["target_resource_id"]
        workspace_id = r.get("workspace_resource_id")
        categories = r.get(
            "log_categories",
            [
                "AppServiceHTTPLogs",
                "AppServicePlatformLogs",
                "AppServiceConsoleLogs",
                "AppServiceAuditLogs",
            ],
        )
        metric_enabled = bool(r.get("metrics", True))
        logs = []
        for c in categories:
            logs.append(
                {"category": c, "enabled": True, "retentionPolicy": {"enabled": False, "days": 0}}
            )
        metrics = [
            {
                "category": "AllMetrics",
                "enabled": metric_enabled,
                "retentionPolicy": {"enabled": False, "days": 0},
            }
        ]
        lines = [
            "resource diag_"
            + str(idx)
            + " 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {",
            "  name: '" + name + "'",
            "  scope: '" + target_id + "'",
            "  properties: {",
            ("    workspaceId: '" + workspace_id + "'," if workspace_id else ""),
            "    logs: " + w.arr(logs) + ",",
            "    metrics: " + w.arr(metrics),
            "  }",
            "}",
            "",
        ]
        return [line for line in lines if line != ""]
