"""Tests for MCP auto-connect on agent startup."""

from __future__ import annotations

from unittest.mock import patch

from coding_agent.tools.mcp.config import MCPConfig, MCPServerConfig


def test_agent_auto_connects_from_config():
    """Agent.from_settings loads mcp.json and connects servers via ToolPool."""
    import tempfile
    from pathlib import Path

    # Temp dir with a mcp.json and a valid env
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        (workdir / ".opencode").mkdir()
        (workdir / ".opencode" / "mcp.json").write_text(
            '{"mcpServers": {"db": {"command": "echo", "args": ["{}"]}}}',
            encoding="utf-8",
        )
        (workdir / ".env").write_text("CODING_AGENT_MODEL=openai:gpt-4o", encoding="utf-8")

        from coding_agent.core import agent as agent_module

        config = MCPConfig(servers={"db": MCPServerConfig(command="echo", args=["{}"])})
        with patch.object(
            agent_module, "find_mcp_config",
            return_value=workdir / ".opencode" / "mcp.json",
        ), patch.object(
            agent_module, "load_mcp_config", return_value=config,
        ):
            agent = agent_module.Agent.from_settings()
            # ToolPool exists and wiring ran without crash
            assert hasattr(agent.tools, "_mcp_clients")
            # Non-matching server dropped silently (echo doesn't speak JSON-RPC)
            assert "db" not in agent.tools._mcp_clients


def test_agent_no_mcp_config_is_safe():
    """Without mcp.json the agent starts fine with no servers."""
    from coding_agent.core import agent as agent_module

    with patch.object(
        agent_module, "find_mcp_config", return_value=None
    ):
        agent = agent_module.Agent.from_settings()
        assert agent.tools._mcp_clients == {}
