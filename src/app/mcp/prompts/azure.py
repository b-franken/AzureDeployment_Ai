from __future__ import annotations

import json

from mcp.server.fastmcp import Context, FastMCP


def register(mcp: FastMCP) -> None:
    @mcp.prompt("provision_from_catalog")
    async def provision_from_catalog(
        context: Context,
        pattern_id: str,
        name: str,
        location: str = "westeurope",
        environment: str = "dev",
        sku: str | None = None,
        owner: str | None = None,
    ) -> str:
        """
        Expands a catalog pattern to a deployment request the user can approve.
        Returns a JSON skeleton for deploy_infrastructure.
        """

        template = {
            "deployment_id": f"{pattern_id}:{name}",
            "validate_only": True,
            "require_approval": True,
            "continue_on_error": False,
            "resources": [],
            "environment": environment,
            "tags": {"owner": owner or "unknown", "environment": environment},
        }
        return json.dumps(template, indent=2)
