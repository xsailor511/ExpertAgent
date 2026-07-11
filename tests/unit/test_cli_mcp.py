"""Tests for MCP CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from coding_agent.cli import app

runner = CliRunner()


def test_mcp_list_no_servers():
    """mcp list shows message when no servers connected."""
    from coding_agent.tools.mcp.pool import ToolPool
    from coding_agent.tools.registry import ToolRegistry

    fake_pool = ToolPool(ToolRegistry())
    fake_agent = MagicMock()
    fake_agent.tools = fake_pool

    with patch("coding_agent.core.agent.Agent.from_settings", return_value=fake_agent):
        result = runner.invoke(app, ["mcp", "list"])

    assert result.exit_code == 0
    assert "没有已连接的 MCP 服务器" in result.stdout


def test_mcp_list_with_servers():
    """mcp list shows connected servers."""
    from coding_agent.tools.mcp.client import MCPClient
    from coding_agent.tools.mcp.pool import ToolPool
    from coding_agent.tools.registry import ToolRegistry

    fake_pool = ToolPool(ToolRegistry())
    fake_pool._mcp_clients["db"] = MCPClient("db", ["echo", "{}"])
    fake_agent = MagicMock()
    fake_agent.tools = fake_pool

    with patch("coding_agent.core.agent.Agent.from_settings", return_value=fake_agent):
        result = runner.invoke(app, ["mcp", "list"])

    assert result.exit_code == 0
    assert "db" in result.stdout
