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
    for name in ("read_file", "write_file", "edit_file", "bash", "search",
                 "glob", "todo_write", "compact",
                 "create_task", "list_tasks", "get_task",
                 "claim_task", "complete_task", "load_skill"):
        assert name in names, f"Missing tool: {name}"

    # 测试 schema 生成
    schemas = registry.schemas()
    assert len(schemas) >= 14
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
