from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from coding_agent.teams.worktree import GitWorktree
from coding_agent.tools.base import Tool, ToolResult


class CreateWorktreeTool(Tool):
    name: ClassVar[str] = "create_worktree"
    description: ClassVar[str] = "Create an isolated git worktree for task execution."
    requires_confirmation: ClassVar[bool] = True

    class Params(BaseModel):
        name: str = Field(..., description="Worktree name (used as directory name)")
        task_id: str = Field("", description="Optional task ID to bind to this worktree")

    def __init__(self, worktree: GitWorktree) -> None:
        self.wt = worktree

    async def execute(self, name: str, task_id: str = "") -> ToolResult:
        try:
            result = self.wt.create(name)
            msg = f"Worktree '{name}' created at {result['path']}"
            if task_id:
                msg += f" (bound to task {task_id})"
            return ToolResult(content=msg)
        except (ValueError, FileExistsError, RuntimeError) as e:
            return ToolResult(content=f"Error: {e}", is_error=True)


class RemoveWorktreeTool(Tool):
    name: ClassVar[str] = "remove_worktree"
    description: ClassVar[str] = "Remove a worktree. Refuses if changes exist."
    requires_confirmation: ClassVar[bool] = True

    class Params(BaseModel):
        name: str = Field(..., description="Worktree name to remove")
        discard_changes: bool = Field(False, description="Force removal even with changes")

    def __init__(self, worktree: GitWorktree) -> None:
        self.wt = worktree

    async def execute(self, name: str, discard_changes: bool = False) -> ToolResult:
        try:
            self.wt.remove(name, force=discard_changes)
            return ToolResult(content=f"Worktree '{name}' removed")
        except (ValueError, RuntimeError) as e:
            return ToolResult(content=f"Error: {e}", is_error=True)


class KeepWorktreeTool(Tool):
    name: ClassVar[str] = "keep_worktree"
    description: ClassVar[str] = "Keep a worktree for manual review."
    requires_confirmation: ClassVar[bool] = False

    class Params(BaseModel):
        name: str = Field(..., description="Worktree name to keep")

    def __init__(self, worktree: GitWorktree) -> None:
        self.wt = worktree

    async def execute(self, name: str) -> ToolResult:
        if not self.wt.exists(name):
            return ToolResult(content=f"Worktree '{name}' not found", is_error=True)
        return ToolResult(content=f"Worktree '{name}' kept for review.")
