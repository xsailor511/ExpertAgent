"""Agent 主类 — 协调 LLM、工具、UI、权限。"""

from __future__ import annotations

from typing import Optional

from coding_agent.config import Settings, get_settings
from coding_agent.core.hooks import (
    HookEvent,
    HookRegistry,
    build_log_hook,
    build_permission_hook,
)
from coding_agent.core.loop import AgentLoop
from coding_agent.core.memory import Memory
from coding_agent.core.recovery import RecoveryState
from coding_agent.core.session import Session
from coding_agent.llm.base import LLMProvider
from coding_agent.llm.router import create_llm
from coding_agent.permissions.policy import PermissionPolicy
from coding_agent.skills.registry import SkillRegistry
from coding_agent.tools.registry import ToolRegistry, create_default_registry
from coding_agent.ui.terminal import TerminalUI
from coding_agent.utils.logging import get_logger, setup_logging

log = get_logger(__name__)

SYSTEM_PROMPT = """\
你是一个在用户代码库中工作的专家编码智能体。

你可以使用工具来读取、编写和编辑文件，运行 shell 命令，以及搜索代码。使用这些工具来完成用户的任务。

指导原则：
1. 在做出更改之前，始终先探索代码库（read_file、search）。
2. 使用 edit_file 进行最小化、有针对性的编辑，而不是重写整个文件。
3. 做出更改后，验证它们（运行测试，重新读取文件）。
4. 解释你在做什么以及为什么这样做，但要简洁。
5. 如果任务有歧义，请要求澄清。
6. 永远不要伪造文件路径或内容 — 始终先读取。

当前工作目录：{workdir}
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
        self.hooks = HookRegistry()
        self.hooks.register(HookEvent.PRE_TOOL_USE, build_log_hook(log))
        self.recovery_state = RecoveryState(primary=settings.model)
        self.loop = AgentLoop(
            llm=llm,
            tools=tools,
            memory=memory,
            ui=ui,
            permissions=permissions,
            hooks=self.hooks,
            recovery_state=self.recovery_state,
        )

    @classmethod
    def from_settings(cls, settings: Optional[Settings] = None) -> "Agent":
        """从配置创建 Agent。"""
        settings = settings or get_settings()
        setup_logging(settings.log_level)

        llm = create_llm(settings=settings)
        tools = create_default_registry(workdir=settings.workdir)
        skill_registry = SkillRegistry()
        skill_registry.scan()
        memory = Memory(
            system_prompt=SYSTEM_PROMPT.format(workdir=settings.workdir),
            max_tokens=settings.max_tokens,
            max_messages=settings.max_history,
            skill_registry=skill_registry,
        )
        session = Session(workdir=settings.workdir)
        ui = TerminalUI()
        permissions = PermissionPolicy(mode=settings.permission, ui=ui)

        agent = cls(
            settings=settings,
            llm=llm,
            tools=tools,
            memory=memory,
            session=session,
            ui=ui,
            permissions=permissions,
        )
        agent.hooks.register(
            HookEvent.PRE_TOOL_USE, build_permission_hook(permissions)
        )
        return agent

    async def run(self, user_input: str) -> str:
        """执行一轮对话。"""
        self.ui.print_user(user_input)
        result = await self.loop.run(user_input)
        self.ui.print_assistant_done()
        return result

    def clear_history(self) -> None:
        """清空对话历史。"""
        self.memory.clear()
        self.ui.print_info("历史记录已清空")

    async def close(self) -> None:
        """释放资源。"""
        await self.llm.close()
        await self.session.close()
