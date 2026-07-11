from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from coding_agent.tools.base import Tool, ToolResult
from coding_agent.tools.mcp.client import MCPClient
from coding_agent.tools.mcp.pool import ToolPool


class ConnectMCPTool(Tool):
    name: ClassVar[str] = "connect_mcp"
    description: ClassVar[str] = (
        "Connect to an MCP server (stdio-based) and discover its tools. "
        "After connection, MCP tools become available as mcp__server__tool."
    )
    requires_confirmation: ClassVar[bool] = False

    class Params(BaseModel):
        name: str = Field(..., description="Server name identifier")
        command: list[str] = Field(
            ...,
            description="Command and args to start the MCP server subprocess",
        )
        env: dict[str, str] | None = Field(None, description="Optional environment variables")

    def __init__(self, pool: ToolPool) -> None:
        self.pool = pool

    async def execute(
        self, name: str, command: list[str], env: dict[str, str] | None = None
    ) -> ToolResult:
        if name in self.pool._mcp_clients:
            return ToolResult(content=f"MCP server '{name}' already connected", is_error=True)
        try:
            client = MCPClient(server_name=name, command=command, env=env)
            client.connect()
            tools = client.discover_tools()
            self.pool.register_mcp(name, client)
            tool_names = [t.get("_original_name", t["name"]) for t in tools]
            return ToolResult(
                content=f"Connected to MCP server '{name}'. "
                f"Discovered {len(tools)} tools: {', '.join(tool_names)}"
            )
        except Exception as e:
            return ToolResult(content=f"MCP connection failed: {e}", is_error=True)
