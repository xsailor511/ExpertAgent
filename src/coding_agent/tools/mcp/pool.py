"""ToolPool — merges builtin tools with MCP-discovered tools."""

from __future__ import annotations

import logging
import threading
from typing import Any

from coding_agent.tools.base import ToolResult
from coding_agent.tools.mcp.client import MCPClient
from coding_agent.tools.mcp.config import MCPConfig
from coding_agent.tools.registry import ToolRegistry


class ToolPool:
    """Combines builtin ToolRegistry tools with MCP-discovered tools.

    MCP tools are prefixed ``mcp__{server}__{tool}`` to avoid name collision.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self._mcp_clients: dict[str, MCPClient] = {}
        self._mcp_tools: dict[str, dict[str, Any]] = {}
        self._mcp_failures: dict[str, str] = {}
        self._mcp_config_servers: list[str] = []
        self._mcp_lock = threading.Lock()

    def register_mcp(self, server_name: str, client: MCPClient) -> None:
        """Register an MCP client and discover its tools."""
        with self._mcp_lock:
            self._mcp_clients[server_name] = client
        tools = client.discover_tools()
        with self._mcp_lock:
            for t in tools:
                self._mcp_tools[t["name"]] = t

    def connect_from_config(self, config: MCPConfig) -> None:
        """Connect to MCP servers in background daemon threads.

        Returns immediately — the app starts without waiting for MCP.
        Connections happen in parallel; results populate ``_mcp_clients``,
        ``_mcp_tools`` and ``_mcp_failures`` as they complete.
        """
        log = logging.getLogger(__name__)
        self._mcp_config_servers = list(config.servers.keys())
        self._mcp_failures.clear()

        for name, server_cfg in config.servers.items():
            with self._mcp_lock:
                if name in self._mcp_clients:
                    log.warning("MCP server '%s' already connected, skipping", name)
                    continue
            cmd_list = [server_cfg.command] + server_cfg.args
            t = threading.Thread(
                target=self._connect_and_register_one,
                args=(name, cmd_list, server_cfg.env),
                daemon=True,
            )
            t.start()

    def _connect_and_register_one(
        self, name: str, command: list[str], env: dict[str, str] | None
    ) -> None:
        """Connect a single MCP server and register its tools (runs in daemon thread)."""
        log = logging.getLogger(__name__)
        try:
            client = MCPClient(server_name=name, command=command, env=env)
            client.connect()
            self.register_mcp(name, client)
            log.info("Connected to MCP server '%s'", name)
        except Exception as e:
            log.warning("Failed to connect MCP server '%s': %s", name, e)
            with self._mcp_lock:
                self._mcp_failures[name] = str(e)

    def get(self, name: str) -> Any | None:
        """Look up a tool by name (builtin or MCP)."""
        if name.startswith("mcp__"):
            return self._mcp_tools.get(name)
        return self.registry.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        """Generate combined tool schemas (builtin + MCP)."""
        builtin_schemas = self.registry.schemas()
        with self._mcp_lock:
            mcp_tools_copy = dict(self._mcp_tools)
        mcp_schemas = []
        for prefixed_name, meta in mcp_tools_copy.items():
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
            with self._mcp_lock:
                client = self._mcp_clients.get(server_name)
            if not client:
                err = self._mcp_failures.get(server_name)
                if err:
                    return ToolResult(
                        content=f"MCP server '{server_name}' connection failed: {err}",
                        is_error=True,
                    )
                return ToolResult(
                    content=(
                        f"MCP server '{server_name}' not yet connected. "
                        "Retry after a moment."
                    ),
                    is_error=True,
                )
            result = await client.call_tool(original_name, arguments)
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

    def set_ui(self, ui: Any) -> None:
        """Propagate UI reference to builtin tools."""
        self.registry.set_ui(ui)

    def close(self) -> None:
        """Close all MCP clients."""
        with self._mcp_lock:
            clients = list(self._mcp_clients.values())
        for client in clients:
            client.close()
