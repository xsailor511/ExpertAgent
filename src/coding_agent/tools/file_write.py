"""文件写入工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import aiofiles
from pydantic import BaseModel, Field

from coding_agent.tools.base import Tool, ToolError, ToolResult
from coding_agent.utils.security import safe_resolve


class FileWriteTool(Tool):
    """写入文件 (覆盖)。"""

    name: ClassVar[str] = "write_file"
    description: ClassVar[str] = (
        "将内容写入文件 (覆盖原有内容)。如果文件所在目录不存在会自动创建。"
        "参数: path (文件路径), content (文件内容)"
    )
    requires_confirmation: ClassVar[bool] = True

    class Params(BaseModel):
        path: str = Field(..., description="目标文件路径")
        content: str = Field(..., description="要写入的内容")

    def __init__(self, workdir: Path) -> None:
        self.workdir = Path(workdir)

    async def execute(self, path: str, content: str, **kwargs: Any) -> ToolResult:
        file_path = safe_resolve(self.workdir, path)

        # 防止写入工作目录之外 (可选, 看需求)
        # 这里允许写入, 但记录日志

        # 创建父目录
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # 备份 (如果文件已存在)
        backup_info = ""
        if file_path.exists():
            backup_info = f" (overwrote {file_path.stat().st_size} bytes)"

        async with aiofiles.open(file_path, mode="w", encoding="utf-8") as f:
            await f.write(content)

        line_count = content.count("\n") + (0 if content.endswith("\n") else 1)
        return ToolResult(
            content=f"Wrote {len(content)} bytes ({line_count} lines) to {path}{backup_info}",
            metadata={"file": str(file_path), "bytes": len(content)},
        )
