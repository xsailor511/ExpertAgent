"""工具注册中心。"""

from __future__ import annotations

from typing import Any

from coding_agent.tools.base import Tool, ToolError, ToolResult
from coding_agent.utils.logging import get_logger

log = get_logger(__name__)


class ToolRegistry:
    """工具注册与执行中心。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册工具。"""
        if tool.name in self._tools:
            log.warning(f"Tool {tool.name} already registered, overwriting")
        self._tools[tool.name] = tool
        log.debug(f"Registered tool: {tool.name}")

    def get(self, name: str) -> Tool | None:
        """获取工具。"""
        return self._tools.get(name)

    def list_names(self) -> list[str]:
        """列出所有工具名。"""
        return list(self._tools.keys())

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def schemas(self) -> list[dict[str, Any]]:
        """生成所有工具的 OpenAI schema。"""
        return [tool.to_openai_schema() for tool in self._tools.values()]

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        approved: bool = False,
    ) -> ToolResult:
        """执行工具。

        Args:
            name: 工具名
            arguments: 参数
            approved: 是否已被用户批准 (用于权限检查)
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(content=f"Unknown tool: {name}", is_error=True)

        if tool.requires_confirmation and not approved:
            return ToolResult(
                content=f"Tool {name} requires confirmation but was not approved",
                is_error=True,
            )

        try:
            # 校验参数
            params = tool.validate(arguments)
            # 执行
            result = await tool.execute(**params.model_dump())
            log.debug(f"Tool {name} executed: {result.content[:100]}...")
            return result
        except ToolError as e:
            log.warning(f"Tool {name} error: {e}")
            return ToolResult(content=str(e), is_error=True)
        except Exception as e:
            log.exception(f"Tool {name} unexpected error")
            return ToolResult(content=f"Unexpected error: {e}", is_error=True)


def create_default_registry(
    workdir: Any,
    llm: Any = None,
    cron_scheduler: Any = None,
    worktree_manager: Any = None,
    team_coordinator: Any = None,
    tool_pool: Any = None,
) -> ToolRegistry:
    """创建默认工具集 (包含所有内置工具)。"""
    from coding_agent.skills.registry import SkillRegistry
    from coding_agent.skills.tool import LoadSkillTool
    from coding_agent.tasks.graph import TaskGraph
    from coding_agent.tasks.store import TaskStore
    from coding_agent.tasks.tools import (
        ClaimTaskTool,
        CompleteTaskTool,
        CreateTaskTool,
        GetTaskTool,
        ListTasksTool,
    )
    from coding_agent.tools.bash import BashTool
    from coding_agent.tools.compact_tool import CompactTool
    from coding_agent.tools.cron_tools import CronCancelTool, CronListTool, CronScheduleTool
    from coding_agent.tools.file_edit import FileEditTool
    from coding_agent.tools.file_read import FileReadTool
    from coding_agent.tools.file_write import FileWriteTool
    from coding_agent.tools.glob_tool import GlobTool
    from coding_agent.tools.mcp_connect_tool import ConnectMCPTool
    from coding_agent.tools.protocol_tools import (
        RequestPlanTool,
        RequestShutdownTool,
        ReviewPlanTool,
    )
    from coding_agent.tools.search import SearchTool
    from coding_agent.tools.subagent_tool import SubagentTool
    from coding_agent.tools.teammate_tools import CheckInboxTool, SendMessageTool, SpawnTeammateTool
    from coding_agent.tools.todo_write_tool import TodoWriteTool
    from coding_agent.tools.worktree_tools import (
        CreateWorktreeTool,
        KeepWorktreeTool,
        RemoveWorktreeTool,
    )

    store = TaskStore()
    graph = TaskGraph(store)
    skill_registry = SkillRegistry()
    skill_registry.scan()

    registry = ToolRegistry()

    # Core file + search tools
    registry.register(FileReadTool(workdir=workdir))
    registry.register(FileWriteTool(workdir=workdir))
    registry.register(FileEditTool(workdir=workdir))
    registry.register(BashTool(workdir=workdir))
    registry.register(SearchTool(workdir=workdir))
    registry.register(GlobTool(workdir=workdir))

    # Skill system
    registry.register(LoadSkillTool(registry=skill_registry))

    # Task graph tools
    registry.register(CreateTaskTool(store=store, graph=graph))
    registry.register(ListTasksTool(store=store))
    registry.register(GetTaskTool(store=store))
    registry.register(ClaimTaskTool(store=store, graph=graph))
    registry.register(CompleteTaskTool(store=store, graph=graph))

    # Session planning
    registry.register(TodoWriteTool())

    # Compaction
    registry.register(CompactTool())

    # Subagent
    if llm:
        registry.register(SubagentTool(llm=llm, workdir=workdir))

    # Cron tools
    if cron_scheduler:
        registry.register(CronScheduleTool(cron_scheduler=cron_scheduler))
        registry.register(CronListTool(cron_scheduler=cron_scheduler))
        registry.register(CronCancelTool(cron_scheduler=cron_scheduler))

    # Worktree tools
    if worktree_manager:
        registry.register(CreateWorktreeTool(worktree=worktree_manager))
        registry.register(RemoveWorktreeTool(worktree=worktree_manager))
        registry.register(KeepWorktreeTool(worktree=worktree_manager))

    # Teammate + protocol tools
    if team_coordinator:
        if llm:
            registry.register(SpawnTeammateTool(
                llm=llm, coordinator=team_coordinator, workdir=workdir,
            ))
        registry.register(SendMessageTool(coordinator=team_coordinator))
        registry.register(CheckInboxTool(coordinator=team_coordinator))
        registry.register(RequestShutdownTool(coordinator=team_coordinator))
        registry.register(RequestPlanTool(coordinator=team_coordinator))
        registry.register(ReviewPlanTool(coordinator=team_coordinator))

    # MCP connect tool
    if tool_pool:
        registry.register(ConnectMCPTool(pool=tool_pool))

    return registry
