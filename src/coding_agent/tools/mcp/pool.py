"""ToolPool — merges builtin tools with MCP-discovered tools."""

from __future__ import annotations

from typing import Any

from coding_agent.tools.base import ToolResult
from coding_agent.tools.mcp.client import MCPClient
from coding_agent.tools.registry import ToolRegistry


class ToolPool:
    """Combines builtin ToolRegistry tools with MCP-discovered tools.

    MCP tools are prefixed ``mcp__{server}__{tool}`` to avoid name collision.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self._mcp_clients: dict[str, MCPClient] = {}
        self._mcp_tools: dict[str, dict[str, Any]] = {}  # prefixed_name -> meta

    def register_mcp(self, server_name: str, client: MCPClient) -> None:
        """Register an MCP client and discover its tools."""
        self._mcp_clients[server_name] = client
        tools = client.discover_tools()
        for t in tools:
            self._mcp_tools[t["name"]] = t

    def get(self, name: str) -> Any | None:
        """Look up a tool by name (builtin or MCP)."""
        if name.startswith("mcp__"):
            return self._mcp_tools.get(name)
        return self.registry.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        """Generate combined tool schemas (builtin + MCP)."""
        builtin_schemas = self.registry.schemas()
        mcp_schemas = []
        for prefixed_name, meta in self._mcp_tools.items():
            mcp_schemas.append({
                "type": "function",
                "function": {
                    "name": prefixed_name,
                    "description": meta.get("description", ""),
                    "parameters": meta.get("inputSchema", {"type": "object", "properties": {}}),
                },
            })
        return builtin_schemas + mcp_schemas

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        **kwargs: Any,
    ) -> ToolResult:
        """Execute a tool. Routes ``mcp__`` prefixed names to MCP clients."""
        if name.startswith("mcp__"):
            parts = name.split("__", 2)
            if len(parts) < 3:
                return ToolResult(
                    content=f"Invalid MCP tool name: {name}",
                    is_error=True,
                )
            server_name = parts[1]
            original_name = parts[2]
            client = self._mcp_clients.get(server_name)
            if not client:
                return ToolResult(
                    content=f"No MCP client for server: {server_name}",
                    is_error=True,
                )
            result = client.call_tool(original_name, arguments)
            content = result.get("content", "")
            if isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict):
                        text_parts.append(item.get("text", str(item)))
                    else:
                        text_parts.append(str(item))
                content = "\n".join(text_parts)
            return ToolResult(
                content=str(content),
                is_error=result.get("is_error", False),
            )
        return await self.registry.execute(name, arguments, **kwargs)

    def close(self) -> None:
        """Close all MCP clients."""
        for client in self._mcp_clients.values():
            client.close()
