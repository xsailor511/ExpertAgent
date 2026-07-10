"""Integration test for tool registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.tools.registry import create_default_registry


@pytest.mark.asyncio
async def test_default_registry(tmp_path: Path) -> None:
    """测试默认工具注册。"""
    registry = create_default_registry(workdir=tmp_path)

    names = registry.list_names()
    assert "read_file" in names
    assert "write_file" in names
    assert "edit_file" in names
    assert "bash" in names
    assert "search" in names
    assert "create_task" in names
    assert "list_tasks" in names
    assert "get_task" in names
    assert "claim_task" in names
    assert "complete_task" in names
    assert "load_skill" in names

    # 测试 schema 生成
    schemas = registry.schemas()
    assert len(schemas) == 11
    for schema in schemas:
        assert schema["type"] == "function"
        assert "name" in schema["function"]
        assert "parameters" in schema["function"]


@pytest.mark.asyncio
async def test_registry_execute_unknown(tmp_path: Path) -> None:
    """测试执行未知工具。"""
    registry = create_default_registry(workdir=tmp_path)
    result = await registry.execute("nonexistent", {})
    assert result.is_error is True
    assert "Unknown tool" in result.content


@pytest.mark.asyncio
async def test_registry_execute_bash(tmp_path: Path) -> None:
    """测试执行 bash 工具。"""
    registry = create_default_registry(workdir=tmp_path)
    result = await registry.execute(
        "bash", {"command": "echo hello"}, approved=True
    )
    assert result.is_error is False
    assert "hello" in result.content
