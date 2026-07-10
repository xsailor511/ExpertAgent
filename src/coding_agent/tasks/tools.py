from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from coding_agent.tasks.graph import TaskGraph
from coding_agent.tasks.models import Task
from coding_agent.tasks.store import TaskStore
from coding_agent.tools.base import Tool, ToolResult


class CreateTaskTool(Tool):
    name: ClassVar[str] = "create_task"
    description: ClassVar[str] = "创建一个新任务，可选择指定依赖"

    class Params(BaseModel):
        subject: str = Field(..., description="任务标题")
        description: str = Field("", description="任务描述")
        blocked_by: list[str] = Field(default_factory=list, description="依赖的任务 ID 列表")

    def __init__(self, store: TaskStore, graph: TaskGraph):
        self.store = store
        self.graph = graph

    async def execute(
        self,
        subject: str,
        description: str = "",
        blocked_by: list[str] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        task = Task(
            id=Task.new_id(),
            subject=subject,
            description=description,
            blocked_by=blocked_by or [],
        )
        self.store.save(task)
        return ToolResult(
            content=f"Created task {task.id}: {task.subject}",
            metadata={"task_id": task.id},
        )


class ListTasksTool(Tool):
    name: ClassVar[str] = "list_tasks"
    description: ClassVar[str] = "列出所有任务及其状态"

    class Params(BaseModel):
        pass

    def __init__(self, store: TaskStore):
        self.store = store

    async def execute(self, **kwargs: Any) -> ToolResult:
        tasks = self.store.list_all()
        if not tasks:
            return ToolResult(content="No tasks found.")
        lines = []
        for t in tasks:
            deps = f" [blocked_by: {', '.join(t.blocked_by)}]" if t.blocked_by else ""
            owner = f" [{t.owner}]" if t.owner else ""
            lines.append(f"  {t.id}: {t.subject} ({t.status}){owner}{deps}")
        return ToolResult(content="Tasks:\n" + "\n".join(lines))


class GetTaskTool(Tool):
    name: ClassVar[str] = "get_task"
    description: ClassVar[str] = "获取任务的详细信息"

    class Params(BaseModel):
        task_id: str = Field(..., description="任务 ID")

    def __init__(self, store: TaskStore):
        self.store = store

    async def execute(self, task_id: str, **kwargs: Any) -> ToolResult:
        task = self.store.load(task_id)
        return ToolResult(content=task.to_dict())


class ClaimTaskTool(Tool):
    name: ClassVar[str] = "claim_task"
    description: ClassVar[str] = "认领一个任务（标记为进行中）"

    class Params(BaseModel):
        task_id: str = Field(..., description="任务 ID")
        owner: str = Field("agent", description="认领人")

    def __init__(self, store: TaskStore, graph: TaskGraph):
        self.store = store
        self.graph = graph

    async def execute(self, task_id: str, owner: str = "agent", **kwargs: Any) -> ToolResult:
        task = self.store.load(task_id)
        if not self.graph.can_start(task):
            blocked = list(task.blocked_by)
            return ToolResult(
                content=f"Cannot claim task {task_id}: still blocked by {', '.join(blocked)}",
                is_error=True,
            )
        task.owner = owner
        task.status = "in_progress"
        self.store.save(task)
        return ToolResult(content=f"Task {task_id} claimed by {owner}")


class CompleteTaskTool(Tool):
    name: ClassVar[str] = "complete_task"
    description: ClassVar[str] = "完成任务，返回解除阻塞的任务列表"

    class Params(BaseModel):
        task_id: str = Field(..., description="任务 ID")

    def __init__(self, store: TaskStore, graph: TaskGraph):
        self.store = store
        self.graph = graph

    async def execute(self, task_id: str, **kwargs: Any) -> ToolResult:
        task = self.store.load(task_id)
        task.status = "completed"
        self.store.save(task)
        unblocked = self.graph.unblocked_by(task_id)
        if unblocked:
            return ToolResult(
                content=f"Task {task_id} completed. Unblocked: {', '.join(unblocked)}",
                metadata={"unblocked": unblocked},
            )
        return ToolResult(content=f"Task {task_id} completed.")
