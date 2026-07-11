"""Tests for tool system."""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.tools.base import ToolError
from coding_agent.tools.file_edit import FileEditTool
from coding_agent.tools.file_read import FileReadTool
from coding_agent.tools.file_write import FileWriteTool


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.mark.asyncio
async def test_file_write_and_read(workdir: Path) -> None:
    """测试写入后读取。"""
    writer = FileWriteTool(workdir=workdir)
    reader = FileReadTool(workdir=workdir)

    # 写入
    result = await writer.execute(path="test.txt", content="hello world\nline 2")
    assert "Wrote" in result.content

    # 读取
    result = await reader.execute(path="test.txt")
    assert "hello world" in result.content
    assert "line 2" in result.content


@pytest.mark.asyncio
async def test_file_read_with_line_range(workdir: Path) -> None:
    """测试行号范围读取。"""
    writer = FileWriteTool(workdir=workdir)
    reader = FileReadTool(workdir=workdir)

    content = "\n".join(f"line {i}" for i in range(1, 11))
    await writer.execute(path="nums.txt", content=content)

    result = await reader.execute(path="nums.txt", start_line=3, end_line=5)
    assert "line 3" in result.content
    assert "line 5" in result.content
    assert "line 6" not in result.content


@pytest.mark.asyncio
async def test_file_edit_replace(workdir: Path) -> None:
    """测试精确编辑。"""
    writer = FileWriteTool(workdir=workdir)
    editor = FileEditTool(workdir=workdir)

    await writer.execute(path="edit.txt", content="foo bar baz")
    result = await editor.execute(
        path="edit.txt", old_str="bar", new_str="qux"
    )
    assert "Edited" in result.content

    reader = FileReadTool(workdir=workdir)
    result = await reader.execute(path="edit.txt")
    assert "foo qux baz" in result.content


@pytest.mark.asyncio
async def test_file_edit_not_found(workdir: Path) -> None:
    """测试编辑不存在的字符串。"""
    writer = FileWriteTool(workdir=workdir)
    editor = FileEditTool(workdir=workdir)

    await writer.execute(path="x.txt", content="hello")
    with pytest.raises(ToolError, match="not found"):
        await editor.execute(path="x.txt", old_str="world", new_str="earth")


@pytest.mark.asyncio
async def test_file_edit_not_unique(workdir: Path) -> None:
    """测试编辑重复字符串。"""
    writer = FileWriteTool(workdir=workdir)
    editor = FileEditTool(workdir=workdir)

    await writer.execute(path="dup.txt", content="a a a")
    with pytest.raises(ToolError, match="appears 3 times"):
        await editor.execute(path="dup.txt", old_str="a", new_str="b")


@pytest.mark.asyncio
async def test_file_read_not_found(workdir: Path) -> None:
    """测试读取不存在的文件。"""
    reader = FileReadTool(workdir=workdir)
    with pytest.raises(ToolError, match="not found"):
        await reader.execute(path="nonexistent.txt")
