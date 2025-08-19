from __future__ import annotations

from typing import Any, cast

from app.mcp.client import MCPClient


class MCPToolProvider:
    def __init__(self) -> None:
        self.client: MCPClient = MCPClient(["python", "-m", "app.mcp.server"])
        self._connected: bool = False

    async def ensure_connected(self) -> None:
        if not self._connected:
            await self.client.connect()
            self._connected = True

    async def list_available_tools(self) -> list[dict[str, Any]]:
        await self.ensure_connected()
        return await self.client.list_tools()

    async def execute(
        self,
        tool_name: str,
        parameters: dict[str, Any],
    ) -> Any:
        await self.ensure_connected()
        return await self.client.execute_tool(tool_name, parameters)

    async def get_resource_context(self, uri: str) -> Any:
        await self.ensure_connected()
        return await self.client.get_resource(uri)

    async def disconnect(self) -> None:
        if self._connected:
            await self.client.disconnect()
            self._connected = False


class MCPContextProvider:
    def __init__(self, mcp_client: MCPClient) -> None:
        self.client: MCPClient = mcp_client

    async def get_azure_context(
        self,
        subscription_id: str,
    ) -> dict[str, Any]:
        resources = await self.client.get_resource(f"azure://resources/{subscription_id}")
        costs = await self.client.get_resource(f"azure://costs/{subscription_id}")
        return {
            "subscription_id": subscription_id,
            "resources": resources,
            "costs": costs,
        }

    async def get_deployment_context(self) -> dict[str, Any]:
        deployments = cast(
            list[Any],
            await self.client.get_resource("deployments://active"),
        )
        return {
            "active_deployments": deployments,
            "deployment_count": len(deployments),
        }
