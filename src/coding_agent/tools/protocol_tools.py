from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from coding_agent.teams.coordinator import TeamCoordinator
from coding_agent.tools.base import Tool, ToolResult


class RequestShutdownTool(Tool):
    name: ClassVar[str] = "request_shutdown"
    description: ClassVar[str] = "Request a teammate to shut down."
    requires_confirmation: ClassVar[bool] = True

    class Params(BaseModel):
        teammate: str = Field(..., description="Name of the teammate to shut down")

    def __init__(self, coordinator: TeamCoordinator) -> None:
        self.coordinator = coordinator

    async def execute(self, teammate: str) -> ToolResult:
        if not self.coordinator.is_teammate_active(teammate):
            return ToolResult(content=f"Teammate '{teammate}' is not active", is_error=True)
        req_id = self.coordinator.send_shutdown_request(teammate)
        return ToolResult(content=f"Shutdown request sent to {teammate} (req: {req_id})")


class RequestPlanTool(Tool):
    name: ClassVar[str] = "request_plan"
    description: ClassVar[str] = "Ask a teammate to submit a plan for review."
    requires_confirmation: ClassVar[bool] = False

    class Params(BaseModel):
        teammate: str = Field(..., description="Name of the teammate")
        task: str = Field(..., description="Task description for the plan")

    def __init__(self, coordinator: TeamCoordinator) -> None:
        self.coordinator = coordinator

    async def execute(self, teammate: str, task: str) -> ToolResult:
        if not self.coordinator.is_teammate_active(teammate):
            return ToolResult(content=f"Teammate '{teammate}' is not active", is_error=True)
        self.coordinator.send_plan_request(teammate, task)
        return ToolResult(content=f"Asked {teammate} to submit a plan for: {task}")


class ReviewPlanTool(Tool):
    name: ClassVar[str] = "review_plan"
    description: ClassVar[str] = "Approve or reject a submitted plan."
    requires_confirmation: ClassVar[bool] = True

    class Params(BaseModel):
        request_id: str = Field(..., description="Request ID from the plan submission")
        approve: bool = Field(..., description="True to approve, False to reject")
        feedback: str = Field("", description="Optional feedback for the teammate")

    def __init__(self, coordinator: TeamCoordinator) -> None:
        self.coordinator = coordinator

    async def execute(self, request_id: str, approve: bool, feedback: str = "") -> ToolResult:
        pending = self.coordinator.get_pending_request(request_id)
        if not pending:
            return ToolResult(content=f"Request {request_id} not found", is_error=True)
        result = self.coordinator.send_plan_response(request_id, approve, feedback)
        if result is None:
            return ToolResult(content=f"Could not resolve request {request_id}", is_error=True)
        action = "approved" if approve else "rejected"
        return ToolResult(content=f"Plan {action} (req: {request_id})")
