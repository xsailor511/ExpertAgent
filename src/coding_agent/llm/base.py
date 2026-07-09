"""LLM 抽象基类与数据结构。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal, Optional

from pydantic import BaseModel


@dataclass
class Message:
    """统一的对话消息格式。"""

    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    # 工具调用相关
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: Optional[str] = None  # role=tool 时使用
    name: Optional[str] = None  # 工具名

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class ToolCall:
    """LLM 发起的工具调用。"""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """LLM 一次完整响应。"""

    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)  # prompt_tokens, completion_tokens


@dataclass
class StreamChunk:
    """流式响应的一个 chunk。"""

    content: str = ""
    tool_call: Optional[ToolCall] = None  # 工具调用（通常在流结束时给出）
    finish_reason: Optional[str] = None


class LLMProvider(ABC):
    """LLM 提供商抽象基类。"""

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.kwargs = kwargs

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """同步对话。"""
        ...

    @abstractmethod
    async def stream(
        self,
        messages: list[Message],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[StreamChunk]:
        """流式对话。"""
        ...
        # 让 mypy 知道这是 async generator
        yield StreamChunk()  # type: ignore[unreachable]

    async def close(self) -> None:
        """释放资源。"""
        pass
