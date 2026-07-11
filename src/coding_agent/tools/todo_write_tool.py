from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from coding_agent.tools.base import Tool, ToolResult

# Module-level in-memory todo list (session-scoped)
_current_todos: list[dict[str, str]] = []


class TodoWriteTool(Tool):
    name: ClassVar[str] = "todo_write"
    description: ClassVar[str] = (
        "Create and manage a task list for the current session. "
        "Use this to plan and track progress."
    )

    class Params(BaseModel):
        todos: list[dict[str, str]] = Field(
            ...,
            description="List of items with 'content' and 'status' (pending/in_progress/completed)",
        )

    async def execute(self, todos: list[dict[str, str]]) -> ToolResult:
        global _current_todos
        errors = self._validate(todos)
        if errors:
            return ToolResult(content=errors, is_error=True)
        _current_todos = todos
        return ToolResult(content=f"Updated {len(_current_todos)} todos")

    @staticmethod
    def _validate(todos: list[dict[str, str]]) -> str | None:
        if not isinstance(todos, list):
            return "Error: todos must be a list"
        valid_statuses = {"pending", "in_progress", "completed"}
        for i, todo in enumerate(todos):
            if not isinstance(todo, dict):
                return f"Error: todos[{i}] must be an object"
            if "content" not in todo or "status" not in todo:
                return f"Error: todos[{i}] missing 'content' or 'status'"
            if todo["status"] not in valid_statuses:
                return f"Error: todos[{i}] has invalid status '{todo['status']}'"
        return None

    @staticmethod
    def get_todos() -> list[dict[str, str]]:
        return list(_current_todos)
