from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from coding_agent.tools.base import Tool, ToolResult


class CompactTool(Tool):
    name: ClassVar[str] = "compact"
    description: ClassVar[str] = (
        "Summarize earlier conversation and continue with compacted context. "
        "Call this when the conversation history is getting long."
    )

    class Params(BaseModel):
        focus: str = Field("", description="Optional: what to focus the summary on")

    async def execute(self, focus: str = "") -> ToolResult:
        return ToolResult(
            content="[Compaction triggered. The loop will summarize history and continue.]"
        )
