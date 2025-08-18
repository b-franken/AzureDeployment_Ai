from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from pydantic import AnyUrl

logger = logging.getLogger(__name__)


class MCPClient:
    def __init__(self, server_command: list[str]):
        self.server_params = StdioServerParameters(
            command=server_command[0],
            args=server_command[1:] if len(server_command) > 1 else [],
        )
        self.session: ClientSession | None = None
        self._stack = AsyncExitStack()
        self._streams: tuple[Any, Any] | None = None

    async def connect(self) -> None:
        if self.session is not None:
            return
        stdio = await self._stack.enter_async_context(stdio_client(self.server_params))
        read, write = stdio
        self._streams = (read, write)
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()

    async def disconnect(self) -> None:
        if self.session is None:
            return
        await self._stack.aclose()
        self.session = None
        self._streams = None
        self._stack = AsyncExitStack()

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        if self.session is None:
            await self.connect()
        assert self.session is not None
        result = await self.session.call_tool(tool_name, arguments)
        return result

    async def get_resource(self, uri: str | AnyUrl) -> Any:
        if self.session is None:
            await self.connect()
        assert self.session is not None
        url = AnyUrl(uri) if isinstance(uri, str) else uri
        resource = await self.session.read_resource(url)
        return resource

    async def list_tools(self) -> list[dict[str, Any]]:
        if self.session is None:
            await self.connect()
        assert self.session is not None
        result = await self.session.list_tools()
        tools = result.tools
        return [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.inputSchema,
            }
            for t in tools
        ]

    async def list_resources(self) -> list[dict[str, Any]]:
        if self.session is None:
            await self.connect()
        assert self.session is not None
        result = await self.session.list_resources()
        resources = result.resources
        return [
            {
                "uri": r.uri,
                "name": r.name,
                "description": r.description,
                "mimeType": r.mimeType,
            }
            for r in resources
        ]


async def main() -> None:
    client = MCPClient(["python", "-m", "app.mcp.server"])
    try:
        await client.connect()
        tools = await client.list_tools()
        logger.info("Available tools: %d", len(tools))
        result = await client.execute_tool(
            "execute_tool",
            {
                "tool_name": "azure_provision",
                "input_text": "create storage account in westeurope",
                "environment": "dev",
                "dry_run": True,
            },
        )
        logger.info("Result: %s", result)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
