"""文件精确编辑工具 — 基于字符串替换。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import aiofiles
from pydantic import BaseModel, Field

from coding_agent.tools.base import Tool, ToolError, ToolResult
from coding_agent.utils.security import safe_resolve


class FileEditTool(Tool):
    """精确编辑文件 — 通过 old_str / new_str 替换。"""

    name: ClassVar[str] = "edit_file"
    description: ClassVar[str] = (
        "通过字符串替换精确编辑文件。"
        "old_str 必须在文件中唯一存在 (否则报错), 会被替换为 new_str。"
        "适用于小范围修改, 避免重写整个文件。"
    )
    requires_confirmation: ClassVar[bool] = True

    class Params(BaseModel):
        path: str = Field(..., description="要编辑的文件路径")
        old_str: str = Field(..., description="要被替换的字符串 (必须唯一)")
        new_str: str = Field(..., description="替换后的字符串")

    def __init__(self, workdir: Path) -> None:
        self.workdir = Path(workdir)

    async def execute(
        self, path: str, old_str: str, new_str: str, **kwargs: Any
    ) -> ToolResult:
        if old_str == new_str:
            raise ToolError("old_str and new_str are identical")

        file_path = safe_resolve(self.workdir, path)
        if not file_path.exists():
            raise ToolError(f"File not found: {path}")

        async with aiofiles.open(file_path, mode="r", encoding="utf-8") as f:
            content = await f.read()

        # 检查唯一性
        occurrences = content.count(old_str)
        if occurrences == 0:
            raise ToolError(
                f"old_str not found in {path}. "
                "Make sure to copy the exact text including whitespace."
            )
        if occurrences > 1:
            raise ToolError(
                f"old_str appears {occurrences} times in {path}. "
                "Provide more context to make it unique."
            )

        # 替换
        new_content = content.replace(old_str, new_str, 1)

        async with aiofiles.open(file_path, mode="w", encoding="utf-8") as f:
            await f.write(new_content)

        # 生成简易 diff
        old_lines = old_str.splitlines()
        new_lines = new_str.splitlines()
        diff = []
        for line in old_lines:
            diff.append(f"- {line}")
        for line in new_lines:
            diff.append(f"+ {line}")

        return ToolResult(
            content=f"Edited {path}:\n" + "\n".join(diff),
            metadata={"file": str(file_path)},
        )
