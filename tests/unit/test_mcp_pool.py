from __future__ import annotations

import pytest

from coding_agent.tools.mcp import ToolPool
from coding_agent.tools.registry import ToolRegistry


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    from pydantic import BaseModel, Field

    from coding_agent.tools.base import Tool, ToolResult

    class MockTool(Tool):
        name = "mock_tool"
        description = "A mock tool"
        requires_confirmation = False

        class Params(BaseModel):
            x: int = Field(..., description="a number")

        async def execute(self, x: int) -> ToolResult:
            return ToolResult(content=f"mocked {x}")

    reg.register(MockTool())
    return reg


def test_pool_schemas_includes_builtin(registry: ToolRegistry):
    pool = ToolPool(registry)
    schemas = pool.schemas()
    names = [s["function"]["name"] for s in schemas]
    assert "mock_tool" in names


def test_pool_schemas_no_mcp_by_default(registry: ToolRegistry):
    pool = ToolPool(registry)
    schemas = pool.schemas()
    assert len(schemas) == 1


def test_execute_builtin_tool(registry: ToolRegistry):
    pool = ToolPool(registry)

    import asyncio

    result = asyncio.run(pool.execute("mock_tool", {"x": 42}))
    assert result.content == "mocked 42"
    assert not result.is_error


def test_execute_unknown_tool(registry: ToolRegistry):
    pool = ToolPool(registry)

    import asyncio

    result = asyncio.run(pool.execute("nonexistent", {}))
    assert result.is_error
    assert "Unknown tool" in result.content


def test_mcp_prefix_routing_no_client(registry: ToolRegistry):
    pool = ToolPool(registry)

    import asyncio

    result = asyncio.run(pool.execute("mcp__server__tool", {}))
    assert result.is_error
    assert "not yet connected" in result.content


def test_mcp_invalid_name_format(registry: ToolRegistry):
    pool = ToolPool(registry)

    import asyncio

    result = asyncio.run(pool.execute("mcp__incomplete", {}))
    assert result.is_error


def test_connect_from_config_success(registry: ToolRegistry):
    """connect_from_config sets servers list immediately; background thread connects later."""
    from coding_agent.tools.mcp.config import MCPConfig, MCPServerConfig

    pool = ToolPool(registry)
    config = MCPConfig(servers={
        "filesystem": MCPServerConfig(
            command="echo", args=["{}"],
        ),
    })
    pool.connect_from_config(config)
    # Servers are recorded immediately, clients connect in background
    assert "filesystem" in pool._mcp_config_servers
    # Client may or may not be populated yet — not guaranteed synchronously


def test_connect_from_config_empty(registry: ToolRegistry):
    """Empty config does nothing."""
    from coding_agent.tools.mcp.config import MCPConfig

    pool = ToolPool(registry)
    pool.connect_from_config(MCPConfig())
    assert pool._mcp_clients == {}
