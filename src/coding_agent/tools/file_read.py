"""文件读取工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Optional

import aiofiles
from pydantic import BaseModel, Field

from coding_agent.tools.base import Tool, ToolError, ToolResult
from coding_agent.utils.security import safe_resolve


class FileReadTool(Tool):
    """读取文件内容。"""

    name: ClassVar[str] = "read_file"
    description: ClassVar[str] = (
        "读取本地文件内容。支持行号范围读取。"
        "参数: path (文件路径), start_line (起始行, 1-based, 可选), "
        "end_line (结束行, 可选)"
    )

    class Params(BaseModel):
        path: str = Field(..., description="要读取的文件路径 (相对工作目录或绝对路径)")
        start_line: Optional[int] = Field(None, ge=1, description="起始行号 (1-based)")
        end_line: Optional[int] = Field(None, ge=1, description="结束行号 (含)")

    def __init__(self, workdir: Path) -> None:
        self.workdir = Path(workdir)

    async def execute(
        self,
        path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        **kwargs: Any,
    ) -> ToolResult:
        file_path = safe_resolve(self.workdir, path)

        if not file_path.exists():
            raise ToolError(f"File not found: {path}")
        if not file_path.is_file():
            raise ToolError(f"Not a file: {path}")

        # 限制文件大小 (10MB)
        size = file_path.stat().st_size
        if size > 10 * 1024 * 1024:
            raise ToolError(f"File too large ({size} bytes), max 10MB")

        async with aiofiles.open(file_path, mode="r", encoding="utf-8", errors="replace") as f:
            content = await f.read()

        lines = content.splitlines(keepends=True)

        # 行号范围
        if start_line is not None or end_line is not None:
            s = (start_line or 1) - 1
            e = end_line or len(lines)
            lines = lines[s:e]

        # 加行号
        numbered = []
        base = start_line or 1
        for i, line in enumerate(lines):
            line_no = base + i
            # 去掉末尾换行以便对齐
            stripped = line.rstrip("\n")
            numbered.append(f"{line_no:>6}\t{stripped}")

        result = "\n".join(numbered)
        total = len(content.splitlines())
        meta = {"total_lines": total, "file": str(file_path)}

        return ToolResult(content=result, metadata=meta)
