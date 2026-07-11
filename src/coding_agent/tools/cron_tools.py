from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from coding_agent.core.cron import CronScheduler
from coding_agent.tools.base import Tool, ToolResult


class CronScheduleTool(Tool):
    name: ClassVar[str] = "schedule_cron"
    description: ClassVar[str] = (
        "Schedule a cron job. cron is 5-field: minute hour day-of-month month day-of-week. "
        "For one-shot reminders, compute the target minute and set recurring=false."
    )
    requires_confirmation: ClassVar[bool] = False

    class Params(BaseModel):
        cron: str = Field(..., description="5-field cron expression (min hour dom month dow)")
        prompt: str = Field(..., description="Prompt to inject when the cron fires")
        recurring: bool = Field(True, description="Whether to repeat after firing")
        durable: bool = Field(True, description="Whether to persist across sessions")

    def __init__(self, cron_scheduler: CronScheduler) -> None:
        self.cron = cron_scheduler

    async def execute(
        self, cron: str, prompt: str, recurring: bool = True, durable: bool = True
    ) -> ToolResult:
        # Validate cron expression
        try:
            fields = cron.strip().split()
            if len(fields) != 5:
                return ToolResult(
                    content=f"Error: expected 5 fields, got {len(fields)}", is_error=True
                )
            bounds = {"min": [0, 59], "hour": [0, 23], "dom": [1, 31],
                       "month": [1, 12], "dow": [0, 6]}
            for field, (lo, hi) in zip(fields, list(bounds.values()), strict=True):
                if field != "*":
                    valid = False
                    for part in field.split(","):
                        part = part.strip()
                        if part.startswith("*/"):
                            valid = part[2:].isdigit()
                        elif "-" in part:
                            a, b = part.split("-", 1)
                            valid = a.isdigit() and b.isdigit() and lo <= int(a) <= int(b) <= hi
                        else:
                            valid = part.isdigit() and lo <= int(part) <= hi
                        if not valid:
                            break
                    if not valid:
                        return ToolResult(
                            content=f"Error: invalid cron field '{field}'", is_error=True
                        )
        except Exception as e:
            return ToolResult(content=f"Error: {e}", is_error=True)

        import time

        from coding_agent.core.cron import CronJob
        job = CronJob(
            id=f"cron_{int(time.time())}_{id(self) % 10000:04d}",
            expr=cron,
            prompt=prompt,
            enabled=True,
        )
        self.cron.add(job)
        return ToolResult(
            content=f"Scheduled {job.id}: '{cron}' -> {prompt[:60]}"
            f" [{'recurring' if recurring else 'one-shot'}{', durable' if durable else ''}]"
        )


class CronListTool(Tool):
    name: ClassVar[str] = "list_crons"
    description: ClassVar[str] = "List registered cron jobs."
    requires_confirmation: ClassVar[bool] = False

    class Params(BaseModel):
        pass

    def __init__(self, cron_scheduler: CronScheduler) -> None:
        self.cron = cron_scheduler

    async def execute(self) -> ToolResult:
        jobs = self.cron.list_jobs()
        if not jobs:
            return ToolResult(content="No cron jobs.")
        lines = []
        for j in jobs:
            status = "enabled" if j.enabled else "disabled"
            lines.append(f"  {j.id}: '{j.expr}' -> {j.prompt[:40]} [{status}]")
        return ToolResult(content="\n".join(lines))


class CronCancelTool(Tool):
    name: ClassVar[str] = "cancel_cron"
    description: ClassVar[str] = "Cancel a cron job by ID."
    requires_confirmation: ClassVar[bool] = False

    class Params(BaseModel):
        job_id: str = Field(..., description="Cron job ID to cancel")

    def __init__(self, cron_scheduler: CronScheduler) -> None:
        self.cron = cron_scheduler

    async def execute(self, job_id: str) -> ToolResult:
        removed = self.cron.remove(job_id)
        if not removed:
            return ToolResult(content=f"Job {job_id} not found", is_error=True)
        return ToolResult(content=f"Cancelled {job_id}")
