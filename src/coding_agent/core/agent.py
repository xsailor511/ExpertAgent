"""Agent 主类 — 协调 LLM、工具、UI、权限。"""

from __future__ import annotations

from typing import Optional

from coding_agent.config import Settings, get_settings
from coding_agent.core.loop import AgentLoop
from coding_agent.core.memory import Memory
from coding_agent.core.session import Session
from coding_agent.llm.base import LLMProvider
from coding_agent.llm.router import create_llm
from coding_agent.permissions.policy import PermissionPolicy
from coding_agent.tools.registry import ToolRegistry, create_default_registry
from coding_agent.ui.terminal import TerminalUI
from coding_agent.utils.logging import get_logger, setup_logging

log = get_logger(__name__)

SYSTEM_PROMPT = """\
You are an expert coding agent working in the user's codebase.

You have access to tools for reading, writing, and editing files, running shell
commands, and searching code. Use them to accomplish the user's task.

Guidelines:
1. Always explore the codebase first (read_file, search) before making changes.
2. Make minimal, targeted edits using edit_file rather than rewriting whole files.
3. After making changes, verify them (run tests, read the file back).
4. Explain what you're doing and why, but be concise.
5. If a task is ambiguous, ask for clarification.
6. Never fabricate file paths or content — always read first.

Current working directory: {workdir}
"""


class Agent:
    """Coding Agent 主类。"""

    def __init__(
        self,
        settings: Settings,
        llm: LLMProvider,
        tools: ToolRegistry,
        memory: Memory,
        session: Session,
        ui: TerminalUI,
        permissions: PermissionPolicy,
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.tools = tools
        self.memory = memory
        self.session = session
        self.ui = ui
        self.permissions = permissions
        self.loop = AgentLoop(
            llm=llm,
            tools=tools,
            memory=memory,
            ui=ui,
            permissions=permissions,
        )

    @classmethod
    def from_settings(cls, settings: Optional[Settings] = None) -> "Agent":
        """从配置创建 Agent。"""
        settings = settings or get_settings()
        setup_logging(settings.log_level)

        llm = create_llm(settings=settings)
        tools = create_default_registry(workdir=settings.workdir)
        memory = Memory(
            system_prompt=SYSTEM_PROMPT.format(workdir=settings.workdir),
            max_tokens=settings.max_tokens,
            max_messages=settings.max_history,
        )
        session = Session(workdir=settings.workdir)
        ui = TerminalUI()
        permissions = PermissionPolicy(mode=settings.permission, ui=ui)

        return cls(
            settings=settings,
            llm=llm,
            tools=tools,
            memory=memory,
            session=session,
            ui=ui,
            permissions=permissions,
        )

    async def run(self, user_input: str) -> str:
        """执行一轮对话。"""
        self.ui.print_user(user_input)
        result = await self.loop.run(user_input)
        self.ui.print_assistant_done()
        return result

    def clear_history(self) -> None:
        """清空对话历史。"""
        self.memory.clear()
        self.ui.print_info("History cleared")

    async def close(self) -> None:
        """释放资源。"""
        await self.llm.close()
        await self.session.close()
