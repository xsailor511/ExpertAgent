"""上下文 / 对话历史管理。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from coding_agent.llm.base import Message
from coding_agent.skills.registry import SkillRegistry
from coding_agent.utils.logging import get_logger
from coding_agent.utils.tokens import estimate_messages_tokens

log = get_logger(__name__)


SYSTEM_IDENTITY = """\
你是一个在用户代码库中工作的专家编码智能体。

你可以使用工具来读取、编写和编辑文件，运行 shell 命令，以及搜索代码。使用这些工具来完成用户的任务。

指导原则：
1. 在做出更改之前，始终先探索代码库（read_file、search）。
2. 使用 edit_file 进行最小化、有针对性的编辑，而不是重写整个文件。
3. 做出更改后，验证它们（运行测试，重新读取文件）。
4. 解释你在做什么以及为什么这样做，但要简洁。
5. 如果任务有歧义，请要求澄清。
6. 永远不要伪造文件路径或内容 — 始终先读取。
"""


class Memory:
    """对话历史与上下文窗口管理。

    功能:
        - 维护 system + user/assistant/tool 消息序列
        - token 计数与超限压缩
        - 保留最近 N 条消息
        - 按需动态组装 system prompt
    """

    def __init__(
        self,
        system_prompt: str | None = None,
        max_tokens: int = 200_000,
        max_messages: int = 50,
        skill_registry: SkillRegistry | None = None,
        workdir: Path | str | None = None,
    ) -> None:
        self._base_prompt = system_prompt or SYSTEM_IDENTITY
        self.max_tokens = max_tokens
        self.max_messages = max_messages
        self.skill_registry = skill_registry
        self.workdir = Path(workdir) if workdir else None
        self.context: dict[str, Any] = {
            "mcp_servers": [],
            "active_teammates": [],
        }
        # 初始 system prompt
        system = self._build_system_prompt()
        self.messages: list[Message] = [Message(role="system", content=system)]

    # --- Per-turn prompt reassembly ---

    def _build_system_prompt(self) -> str:
        """Rebuild the system prompt from current context (skills, MCP, time)."""
        sections = [self._base_prompt.strip()]
        if self.workdir:
            sections.append(f"工作目录：{self.workdir}")
        sections.append(f"当前时间：{datetime.now().isoformat(timespec='seconds')}")

        # Skills catalog
        if self.skill_registry:
            skills = self.skill_registry.list_skill_dicts()
            if skills:
                catalog = "\n".join(f"- {s['name']}: {s['description']}" for s in skills)
                sections.append(f"可用技能：\n{catalog}\n使用 load_skill(name) 加载需要的技能。")

        # MCP servers
        mcp = self.context.get("mcp_servers", [])
        if mcp:
            sections.append(
                f"已连接 MCP 服务器：{', '.join(mcp)}\n"
                "使用 mcp__{server}__{tool_name} 格式调用 MCP 工具。\n"
                "运行 'coding-agent mcp list' 查看详情。"
            )

        # Active teammates
        teammates = self.context.get("active_teammates", [])
        if teammates:
            sections.append(f"活跃队友：{', '.join(teammates)}")

        return "\n\n".join(sections)

    def refresh_system_prompt(self) -> None:
        """Rebuild the system prompt per-turn and update it in place."""
        new = self._build_system_prompt()
        if self.messages and self.messages[0].role == "system":
            self.messages[0] = Message(role="system", content=new)
        else:
            self.messages.insert(0, Message(role="system", content=new))

    def add_user(self, content: str) -> None:
        self.messages.append(Message(role="user", content=content))
        self._maybe_compress()

    def add_assistant(
        self,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
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
        self.messages = [Message(role="system", content=self._build_system_prompt())]

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
    def from_json(cls, data: str, system_prompt: str | None = None) -> Memory:
        """从 JSON 反序列化。"""
        mem = cls(system_prompt=system_prompt)
        items = json.loads(data)
        mem.messages = [Message(**item) for item in items]
        return mem
