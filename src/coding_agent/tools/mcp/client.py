"""Lightweight MCP client for stdio-based servers."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from contextlib import suppress
from typing import Any


class MCPClient:
    """Connects to a stdio-based MCP server to discover and call tools."""

    # stderr is redirected to DEVNULL to eliminate pipe-buffer deadlock:
    # when the server writes enough log data to stderr, the OS pipe buffer
    # fills up, the server blocks on write, and the client (waiting on
    # stdout) deadlocks with it.  DEVNULL sidesteps the problem entirely.

    def __init__(
        self, server_name: str, command: list[str], env: dict[str, str] | None = None
    ) -> None:
        self.server_name = server_name
        self.command = command
        self.env = {**env} if env else None
        self._process: subprocess.Popen | None = None
        self._tools: list[dict[str, Any]] = []
        self._req_id = 0

    def connect(self) -> None:
        """Start the MCP server subprocess and do the initialize handshake."""
        merged_env = None
        if self.env:
            merged_env = {**os.environ, **self.env}
        # On Windows, commands like ``npx`` (npx.cmd) need shell=True
        # because CreateProcess only resolves .exe files from PATH.
        use_shell = os.name == "nt" and not os.path.isabs(self.command[0])
        self._process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=merged_env,
            shell=use_shell,
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
        # Per MCP spec, client MUST send initialized notification after
        # receiving InitializeResult, before any other requests.
        self._send_notification("notifications/initialized")

    def _send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        notification: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params:
            notification["params"] = params
        line = json.dumps(notification) + "\n"
        self._process.stdin.write(line)
        self._process.stdin.flush()

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

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool by its original (unprefixed) name (async with timeout).

        Returns a dict with ``is_error`` on timeout or transport failure so the
        LLM can decide how to react (retry, fix args, etc.).
        """
        self._req_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        try:
            resp = await self._send_async(request, timeout=40.0)
        except TimeoutError:
            return {
                "content": f"MCP tool '{name}' timed out after 40s on server '{self.server_name}'",
                "is_error": True,
            }
        except RuntimeError as e:
            return {"content": str(e), "is_error": True}
        if not resp:
            return {"content": "No response from MCP server", "is_error": True}
        if "error" in resp:
            return {"content": str(resp["error"]), "is_error": True}
        result = resp.get("result", {})
        return result

    def close(self) -> None:
        """Close stdin first (signals server to exit), then terminate the subprocess."""
        if not self._process:
            return
        # Close stdin to tell the server to stop reading (graceful hint)
        if self._process.stdin and not self._process.stdin.closed:
            with suppress(OSError):
                self._process.stdin.close()
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()

    @staticmethod
    def _read_stderr(process: subprocess.Popen) -> str:
        """Read stderr safely, handling encoding errors."""
        if not process.stderr:
            return "(stderr discarded via DEVNULL)"
        try:
            return process.stderr.read()
        except (UnicodeDecodeError, ValueError):
            pass
        if hasattr(process.stderr, "buffer"):
            try:
                return process.stderr.buffer.read().decode("utf-8", errors="replace")
            except Exception:
                pass
        return "(stderr could not be decoded)"

    def _send(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Send a JSON-RPC request and read the response (blocking, no timeout).

        Used only during startup (connect / discover_tools). For runtime tool
        calls prefer ``_send_async`` which has a timeout.
        """
        if not self._process or not self._process.stdin or not self._process.stdout:
            return None
        line = json.dumps(request) + "\n"
        self._process.stdin.write(line)
        self._process.stdin.flush()
        response_line = self._process.stdout.readline()
        if not response_line:
            stderr_output = self._read_stderr(self._process)
            raise RuntimeError(
                f"MCP server '{self.server_name}' closed stdout. stderr: {stderr_output.strip()}"
            )
        try:
            return json.loads(response_line)
        except json.JSONDecodeError as e:
            stderr_output = self._read_stderr(self._process)
            raise RuntimeError(
                f"MCP server '{self.server_name}' returned invalid JSON. "
                f"stdout: {response_line.strip()!r}, stderr: {stderr_output.strip()}"
            ) from e

    async def _send_async(
        self, request: dict[str, Any], timeout: float = 30.0
    ) -> dict[str, Any] | None:
        """Send a JSON-RPC request and read the response (async with timeout).

        Runs the blocking I/O in a thread pool so the event loop stays responsive.
        Raises ``TimeoutError`` if the server does not respond within ``timeout`` seconds.
        """
        if not self._process or not self._process.stdin or not self._process.stdout:
            return None
        line = json.dumps(request) + "\n"
        self._process.stdin.write(line)
        self._process.stdin.flush()
        try:
            response_line = await asyncio.wait_for(
                asyncio.to_thread(self._process.stdout.readline),
                timeout=timeout,
            )
        except TimeoutError:
            raise TimeoutError(
                f"MCP server '{self.server_name}' did not respond within {timeout}s"
            ) from None
        if not response_line:
            stderr_output = self._read_stderr(self._process)
            raise RuntimeError(
                f"MCP server '{self.server_name}' closed stdout. stderr: {stderr_output.strip()}"
            )
        try:
            return json.loads(response_line)
        except json.JSONDecodeError as e:
            stderr_output = self._read_stderr(self._process)
            raise RuntimeError(
                f"MCP server '{self.server_name}' returned invalid JSON. "
                f"stdout: {response_line.strip()!r}, stderr: {stderr_output.strip()}"
            ) from e
