"""Agent 主类 — 协调 LLM、工具、UI、权限。"""

from __future__ import annotations

from pathlib import Path

from coding_agent.config import Settings, get_settings
from coding_agent.core.background import BackgroundTaskManager
from coding_agent.core.cron import CronScheduler
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
from coding_agent.teams.bus import MessageBus
from coding_agent.teams.coordinator import TeamCoordinator
from coding_agent.teams.worktree import GitWorktree
from coding_agent.tools.mcp.config import find_mcp_config, load_mcp_config
from coding_agent.tools.mcp.pool import ToolPool
from coding_agent.tools.registry import ToolRegistry, create_default_registry
from coding_agent.ui.terminal import TerminalUI
from coding_agent.utils.logging import get_logger, setup_logging

log = get_logger(__name__)


class Agent:
    """Coding Agent 主类。"""

    def __init__(
        self,
        settings: Settings,
        llm: LLMProvider,
        tools: ToolRegistry | ToolPool,
        memory: Memory,
        session: Session,
        ui: TerminalUI,
        permissions: PermissionPolicy,
        bg_manager: BackgroundTaskManager | None = None,
        cron_scheduler: CronScheduler | None = None,
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.tools = tools
        self.memory = memory
        self.session = session
        self.ui = ui
        self.permissions = permissions
        self.bg_manager = bg_manager
        self.cron = cron_scheduler
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
            bg_manager=self.bg_manager,
            cron_scheduler=self.cron,
        )

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> Agent:
        """从配置创建 Agent。"""
        settings = settings or get_settings()
        setup_logging(settings.log_level)

        llm = create_llm(settings=settings)
        skill_registry = SkillRegistry()
        skill_registry.scan()

        # Infrastructure
        session = Session(workdir=settings.workdir)
        ui = TerminalUI()
        permissions = PermissionPolicy(mode=settings.permission, ui=ui)
        bg_manager = BackgroundTaskManager()
        cron_scheduler = CronScheduler()
        cron_scheduler.start()
        bus = MessageBus()
        coordinator = TeamCoordinator(bus=bus)
        worktree_manager = GitWorktree(repo_path=Path(settings.workdir))

        # Tool registry (builtin tools only)
        tools = create_default_registry(
            workdir=settings.workdir,
            llm=llm,
            cron_scheduler=cron_scheduler,
            worktree_manager=worktree_manager,
            team_coordinator=coordinator,
        )
        # ToolPool wraps ToolRegistry and adds MCP tool support
        tool_pool = ToolPool(registry=tools)
        # Re-register connect_mcp with the pool reference
        from coding_agent.tools.mcp_connect_tool import ConnectMCPTool

        tools.register(ConnectMCPTool(pool=tool_pool))

        memory = Memory(
            max_tokens=settings.max_tokens,
            max_messages=settings.max_history,
            skill_registry=skill_registry,
            workdir=settings.workdir,
        )

        # Auto-connect MCP servers from mcp.json config (failures are dropped)
        mcp_config_path = find_mcp_config(Path(settings.workdir))
        if mcp_config_path:
            mcp_config = load_mcp_config(mcp_config_path)
            tool_pool.connect_from_config(mcp_config)
            memory.context["mcp_servers"] = list(tool_pool._mcp_clients.keys())

        agent = cls(
            settings=settings,
            llm=llm,
            tools=tool_pool,
            memory=memory,
            session=session,
            ui=ui,
            permissions=permissions,
            bg_manager=bg_manager,
            cron_scheduler=cron_scheduler,
        )
        agent.hooks.register(HookEvent.PRE_TOOL_USE, build_permission_hook(permissions))
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
        if self.cron:
            self.cron.stop()
        await self.llm.close()
        await self.session.close()
