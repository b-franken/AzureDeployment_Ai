from __future__ import annotations

import os

from app.mcp.server import MCPServer

if __name__ == "__main__":
    os.environ.setdefault("MCP_TRANSPORT", "streamable-http")
    server = MCPServer(transport="streamable-http")
    server.run()
