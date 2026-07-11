from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field

from coding_agent.tools.base import Tool, ToolResult


class GlobTool(Tool):
    name: ClassVar[str] = "glob"
    description: ClassVar[str] = "Find files matching a glob pattern (e.g. **/*.py)."

    class Params(BaseModel):
        pattern: str = Field(..., description="Glob pattern to search for")

    def __init__(self, workdir: Path) -> None:
        self.workdir = Path(workdir)

    async def execute(self, pattern: str) -> ToolResult:
        try:
            import glob as g
            results = []
            for match in g.glob(pattern, root_dir=self.workdir):
                if (self.workdir / match).resolve().is_relative_to(self.workdir):
                    results.append(match)
            if not results:
                return ToolResult(content="(no matches)")
            return ToolResult(content="\n".join(sorted(results)))
        except Exception as e:
            return ToolResult(content=f"Error: {e}", is_error=True)
