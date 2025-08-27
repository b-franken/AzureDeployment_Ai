from __future__ import annotations

import json
from typing import Any

from app.tools.base import ToolResult

# Import the cache function to store rich outputs
try:
    from app.api.services import cache_rich_output
except ImportError:
    def cache_rich_output(correlation_id: str, output: str) -> None:
        pass  # Fallback if import fails


def ok(summary: str, obj: dict | str = "") -> ToolResult:
    if isinstance(obj, dict) and "infrastructure_code" in obj:
        formatted_output = format_deployment_preview(obj)
        # Cache the rich output for potential use by services layer
        if correlation_id := obj.get("parameters", {}).get("correlation_id"):
            cache_rich_output(correlation_id, formatted_output)
    else:
        formatted_output = obj if isinstance(obj, str) else json.dumps(obj, default=str, indent=2)
    
    return {
        "ok": True,
        "summary": summary,
        "output": formatted_output,
    }


def format_deployment_preview(data: dict) -> str:
    lines = [
        f"**{data.get('summary', 'Deployment Preview')}**",
        "",
        f"**Deployment ID:** `{data.get('deployment_id', 'N/A')}`",
        f"**Environment:** {data.get('environment', 'dev')}",
        f"**Location:** {data.get('location', 'westeurope')}",
        f"**Resource Group:** {data.get('resource_group', 'N/A')}",
        "",
        "## Resource Details",
    ]
    
    if data.get("resource_details"):
        for key, value in data["resource_details"].items():
            lines.append(f"- **{key.replace('_', ' ').title()}:** {value}")
        lines.append("")
    
    if data.get("cost_estimate"):
        lines.extend([
            "## Estimated Monthly Cost",
            f"**${data['cost_estimate'].get('monthly_estimate', '0.00')}** USD/month",
            "",
        ])
    
    if data.get("infrastructure_code"):
        if bicep := data["infrastructure_code"].get("bicep"):
            lines.extend([
                "## Bicep Infrastructure Code",
                "```bicep",
                bicep,
                "```",
                "",
            ])
        
        if terraform := data["infrastructure_code"].get("terraform"):
            lines.extend([
                "## Terraform Infrastructure Code", 
                "```hcl",
                terraform,
                "```",
                "",
            ])
    
    if validation := data.get("validation"):
        lines.extend([
            "## Validation Results",
            f"- **Warnings:** {validation.get('warnings', 0)}",
            f"- **Errors:** {validation.get('errors', 0)}",
            f"- **Critical:** {validation.get('critical', 0)}",
            "",
        ])
        
        if failed_rules := validation.get("failed"):
            lines.append("**Failed Validation Rules:**")
            for rule in failed_rules[:3]:
                lines.append(f"- {rule['severity'].upper()}: {rule['message']}")
            lines.append("")
    
    if next_steps := data.get("next_steps"):
        lines.extend([
            "## Next Steps",
        ])
        for i, step in enumerate(next_steps, 1):
            lines.append(f"{i}. {step}")
        lines.append("")
    
    if data.get("warning"):
        lines.extend([
            "## Warning",
            data["warning"],
        ])
    
    return "\n".join(lines)


def err(summary: str, msg: str) -> ToolResult:
    return {"ok": False, "summary": summary, "output": msg}


def dry(summary: str, payload: dict) -> ToolResult:
    return ok(summary, {"dry_run": True, **payload})
