"""Lightweight MCP client for stdio-based servers."""

from __future__ import annotations

import json
import subprocess
from typing import Any


class MCPClient:
    """Connects to a stdio-based MCP server to discover and call tools."""

    def __init__(
        self, server_name: str, command: list[str], env: dict[str, str] | None = None
    ) -> None:
        self.server_name = server_name
        self.command = command
        self.env = {**env} if env else None
        self._process: subprocess.Popen | None = None
        self._tools: list[dict[str, Any]] = []

    def connect(self) -> None:
        """Start the MCP server subprocess and do the initialize handshake."""
        self._process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self.env,
        )
        # Initialize
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "coding-agent", "version": "0.1.0"},
            },
        }
        resp = self._send(init_request)
        if not resp or "error" in resp:
            raise RuntimeError(f"MCP init failed: {resp}")

    def discover_tools(self) -> list[dict[str, Any]]:
        """Call tools/list and return the tool definitions with MCP prefix."""
        request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        resp = self._send(request)
        if not resp or "error" in resp:
            return []
        tools_raw = resp.get("result", {}).get("tools", [])
        self._tools = []
        for t in tools_raw:
            prefixed = dict(t)
            prefixed["name"] = f"mcp__{self.server_name}__{t['name']}"
            prefixed["_original_name"] = t["name"]
            self._tools.append(prefixed)
        return self._tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool by its original (unprefixed) name."""
        request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        resp = self._send(request)
        if not resp:
            return {"content": "No response from MCP server", "is_error": True}
        if "error" in resp:
            return {"content": str(resp["error"]), "is_error": True}
        result = resp.get("result", {})
        return result

    def close(self) -> None:
        """Terminate the server subprocess."""
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()

    def _send(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Send a JSON-RPC request and read the response."""
        if not self._process or not self._process.stdin or not self._process.stdout:
            return None
        line = json.dumps(request) + "\n"
        self._process.stdin.write(line)
        self._process.stdin.flush()
        response_line = self._process.stdout.readline()
        if not response_line:
            return None
        return json.loads(response_line)
