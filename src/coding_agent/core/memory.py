"""上下文 / 对话历史管理。"""

from __future__ import annotations

import json
from typing import Any, Optional

from coding_agent.llm.base import Message
from coding_agent.utils.logging import get_logger
from coding_agent.utils.tokens import count_tokens, estimate_messages_tokens

log = get_logger(__name__)


class Memory:
    """对话历史与上下文窗口管理。

    功能:
        - 维护 system + user/assistant/tool 消息序列
        - token 计数与超限压缩
        - 保留最近 N 条消息
    """

    def __init__(
        self,
        system_prompt: str,
        max_tokens: int = 200_000,
        max_messages: int = 50,
    ) -> None:
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.max_messages = max_messages
        self.messages: list[Message] = [Message(role="system", content=system_prompt)]

    def add_user(self, content: str) -> None:
        self.messages.append(Message(role="user", content=content))
        self._maybe_compress()

    def add_assistant(
        self,
        content: str,
        tool_calls: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        self.messages.append(
            Message(role="assistant", content=content, tool_calls=tool_calls or [])
        )
        self._maybe_compress()

    def add_tool(self, tool_call_id: str, name: str, content: str) -> None:
        self.messages.append(
            Message(
                role="tool",
                content=content,
                tool_call_id=tool_call_id,
                name=name,
            )
        )
        self._maybe_compress()

    def clear(self) -> None:
        """清空历史 (保留 system prompt)。"""
        self.messages = [Message(role="system", content=self.system_prompt)]

    def token_count(self) -> int:
        """估算当前消息总 token 数。"""
        return estimate_messages_tokens([m.to_dict() for m in self.messages])

    def _maybe_compress(self) -> None:
        """如果超限，压缩历史 (保留 system + 最近若干条)。"""
        # 1. 消息数限制
        if len(self.messages) > self.max_messages + 1:  # +1 for system
            # 保留 system + 最近 max_messages 条
            keep = self.messages[:1] + self.messages[-self.max_messages:]
            dropped = len(self.messages) - len(keep)
            log.debug(f"压缩记忆：删除了 {dropped} 条旧消息")
            self.messages = keep

        # 2. token 限制
        if self.token_count() > self.max_tokens:
            # 激进压缩: 只保留 system + 最近 10 条
            keep_count = min(10, len(self.messages) - 1)
            keep = self.messages[:1] + self.messages[-keep_count:]
            log.warning(
                f"超过 token 限制，已激进一步压缩至 {len(keep)} 条消息"
            )
            self.messages = keep

    def to_json(self) -> str:
        """序列化为 JSON (用于持久化)。"""
        return json.dumps([m.to_dict() for m in self.messages], ensure_ascii=False)

    @classmethod
    def from_json(cls, data: str, system_prompt: str) -> "Memory":
        """从 JSON 反序列化。"""
        mem = cls(system_prompt=system_prompt)
        items = json.loads(data)
        mem.messages = [Message(**item) for item in items]
        return mem
