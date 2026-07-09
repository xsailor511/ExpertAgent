"""Tests for memory management."""

from __future__ import annotations

import pytest

from coding_agent.core.memory import Memory


def test_memory_basic() -> None:
    """测试基本的消息添加。"""
    mem = Memory(system_prompt="You are helpful.", max_messages=10)
    assert len(mem.messages) == 1
    assert mem.messages[0].role == "system"

    mem.add_user("Hello")
    assert len(mem.messages) == 2
    assert mem.messages[1].role == "user"
    assert mem.messages[1].content == "Hello"

    mem.add_assistant("Hi there!")
    assert len(mem.messages) == 3
    assert mem.messages[2].role == "assistant"


def test_memory_clear() -> None:
    """测试清空历史。"""
    mem = Memory(system_prompt="test")
    mem.add_user("a")
    mem.add_assistant("b")
    assert len(mem.messages) == 3

    mem.clear()
    assert len(mem.messages) == 1
    assert mem.messages[0].role == "system"


def test_memory_compression() -> None:
    """测试消息数超限压缩。"""
    mem = Memory(system_prompt="test", max_messages=5)
    for i in range(20):
        mem.add_user(f"msg {i}")
        mem.add_assistant(f"resp {i}")

    # 应该被压缩到 system + max_messages
    assert len(mem.messages) <= 6  # 1 system + 5 recent


def test_memory_tool_message() -> None:
    """测试工具消息。"""
    mem = Memory(system_prompt="test")
    mem.add_user("list files")
    mem.add_assistant(
        content="",
        tool_calls=[{"id": "tc1", "type": "function", "function": {"name": "bash", "arguments": "{}"}}],
    )
    mem.add_tool("tc1", "bash", "file1.txt\nfile2.txt")

    assert len(mem.messages) == 4
    assert mem.messages[3].role == "tool"
    assert mem.messages[3].tool_call_id == "tc1"
    assert mem.messages[3].name == "bash"


def test_memory_serialization() -> None:
    """测试序列化与反序列化。"""
    mem = Memory(system_prompt="test prompt")
    mem.add_user("hello")
    mem.add_assistant("hi")

    data = mem.to_json()
    mem2 = Memory.from_json(data, system_prompt="test prompt")

    assert len(mem2.messages) == len(mem.messages)
    assert mem2.messages[1].content == "hello"
    assert mem2.messages[2].content == "hi"
