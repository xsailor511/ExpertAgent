"""工具注册中心。"""

from __future__ import annotations

from typing import Any, Optional

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

    def get(self, name: str) -> Optional[Tool]:
        """获取工具。"""
        return self._tools.get(name)

    def list_names(self) -> list[str]:
        """列出所有工具名。"""
        return list(self._tools.keys())

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


def create_default_registry(workdir: Any) -> ToolRegistry:
    """创建默认工具集。"""
    from coding_agent.tools.bash import BashTool
    from coding_agent.tools.file_edit import FileEditTool
    from coding_agent.tools.file_read import FileReadTool
    from coding_agent.tools.file_write import FileWriteTool
    from coding_agent.tools.search import SearchTool

    registry = ToolRegistry()
    registry.register(FileReadTool(workdir=workdir))
    registry.register(FileWriteTool(workdir=workdir))
    registry.register(FileEditTool(workdir=workdir))
    registry.register(BashTool(workdir=workdir))
    registry.register(SearchTool(workdir=workdir))
    return registry
