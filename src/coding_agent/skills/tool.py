from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from coding_agent.skills.registry import SkillRegistry
from coding_agent.tools.base import Tool, ToolResult


class LoadSkillTool(Tool):
    name: ClassVar[str] = "load_skill"
    description: ClassVar[str] = (
        "Load the full content of a skill by name. "
        "Skills provide specialized instructions and workflows."
    )
    requires_confirmation: ClassVar[bool] = False

    class Params(BaseModel):
        name: str = Field(..., description="Name of the skill to load")

    def __init__(self, registry: SkillRegistry):
        self.registry = registry

    async def execute(self, name: str) -> ToolResult:
        content = self.registry.get_enriched_content(name)
        if content is None:
            return ToolResult(
                content=f"Skill '{name}' not found. Available: {self.registry.available_skills()}",
                is_error=True,
            )
        return ToolResult(content=content)
