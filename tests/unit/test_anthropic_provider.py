from __future__ import annotations

import pytest

from coding_agent.llm.anthropic_provider import HAS_ANTHROPIC, AnthropicProvider
from coding_agent.llm.base import Message


def test_import_check():
    assert isinstance(HAS_ANTHROPIC, bool)


def test_init_without_sdk():
    if not HAS_ANTHROPIC:
        with pytest.raises(ImportError):
            AnthropicProvider(model="claude-3-5-sonnet-latest")


def test_convert_messages(text_messages):
    if not HAS_ANTHROPIC:
        pytest.skip("anthropic SDK not installed")
    provider = AnthropicProvider(model="claude-3-5-sonnet-latest", api_key="test")
    result = provider._convert_messages(text_messages)
    assert provider._system == "You are a helpful assistant."
    assert result[0]["role"] == "user"
    assert result[0]["content"] == "Hello"


def test_convert_messages_with_tool_calls(text_messages_with_tool):
    if not HAS_ANTHROPIC:
        pytest.skip("anthropic SDK not installed")
    provider = AnthropicProvider(model="claude-3-5-sonnet-latest", api_key="test")
    result = provider._convert_messages(text_messages_with_tool)
    assistant_msgs = [m for m in result if m["role"] == "assistant"]
    tool_assistant = [m for m in assistant_msgs if isinstance(m.get("content"), list)]
    assert len(tool_assistant) >= 1
    blocks = tool_assistant[0]["content"]
    tool_uses = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use"]
    assert len(tool_uses) >= 1


def test_convert_tools(tool_schemas):
    if not HAS_ANTHROPIC:
        pytest.skip("anthropic SDK not installed")
    provider = AnthropicProvider(model="claude-3-5-sonnet-latest", api_key="test")
    result = provider._convert_tools(tool_schemas)
    assert len(result) >= 1
    assert "name" in result[0]
    assert "input_schema" in result[0]


def test_convert_tool_message(text_messages_with_tool):
    if not HAS_ANTHROPIC:
        pytest.skip("anthropic SDK not installed")
    provider = AnthropicProvider(model="claude-3-5-sonnet-latest", api_key="test")
    result = provider._convert_messages(text_messages_with_tool)
    tool_msgs = [m for m in result if m["role"] == "user" and isinstance(m.get("content"), list)]
    tool_results = []
    for m in tool_msgs:
        for block in m["content"]:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                tool_results.append(block)
    assert len(tool_results) >= 1
    assert tool_results[0]["tool_use_id"] == "tc_01"
    assert tool_results[0]["content"] == "Sunny 72\u00b0F"


@pytest.fixture
def text_messages():
    return [
        Message(role="system", content="You are a helpful assistant."),
        Message(role="user", content="Hello"),
    ]


@pytest.fixture
def text_messages_with_tool():
    return [
        Message(role="user", content="What's the weather?"),
        Message(
            role="assistant",
            content="",
            tool_calls=[{
                "id": "tc_01",
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "arguments": '{"location": "NYC"}',
                },
            }],
        ),
        Message(
            role="tool",
            content="Sunny 72°F",
            tool_call_id="tc_01",
            name="get_weather",
        ),
    ]


@pytest.fixture
def tool_schemas():
    return [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather for a location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "City name"},
                    },
                },
            },
        }
    ]
