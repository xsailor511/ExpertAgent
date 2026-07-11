"""代码搜索工具 — 基于 ripgrep。"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from coding_agent.tools.base import Tool, ToolError, ToolResult


class SearchTool(Tool):
    """使用 ripgrep 在工作目录中搜索。"""

    name: ClassVar[str] = "search"
    description: ClassVar[str] = (
        "使用 ripgrep 在工作目录中搜索文本或正则。"
        "参数: pattern (搜索模式), glob (文件名 glob, 可选, 如 '*.py'), "
        "max_results (最大结果数, 默认 50)"
    )

    class Params(BaseModel):
        pattern: str = Field(..., description="搜索模式 (支持正则)")
        glob: str | None = Field(None, description="文件名过滤, 如 '*.py'")
        max_results: int = Field(50, ge=1, le=500)

    def __init__(self, workdir: Path) -> None:
        self.workdir = Path(workdir)

    async def execute(
        self,
        pattern: str,
        glob: str | None = None,
        max_results: int = 50,
        **kwargs: Any,
    ) -> ToolResult:
        # 检查 ripgrep 是否安装
        rg_path = shutil.which("rg")
        if rg_path is None:
            # 降级到 Python 内置搜索
            return await self._fallback_search(pattern, glob, max_results)

        import asyncio

        cmd = [
            rg_path,
            "--line-number",
            "--no-heading",
            "--color=never",
            "--max-count", str(max_results),
        ]
        if glob:
            cmd.extend(["--glob", glob])
        cmd.extend([pattern, str(self.workdir)])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
        except TimeoutError:
            raise ToolError("Search timed out")

        output = stdout.decode("utf-8", errors="replace")
        if not output:
            return ToolResult(content=f"No matches for: {pattern}")

        # 限制结果数
        lines = output.strip().splitlines()
        if len(lines) > max_results:
            lines = lines[:max_results]
            lines.append(f"... ({len(lines)} results shown, truncated)")

        return ToolResult(
            content="\n".join(lines),
            metadata={"pattern": pattern, "match_count": len(lines)},
        )

    async def _fallback_search(
        self, pattern: str, glob: str | None, max_results: int
    ) -> ToolResult:
        """无 ripgrep 时的降级搜索。"""
        import fnmatch
        import re

        try:
            regex = re.compile(pattern)
        except re.error as e:
            raise ToolError(f"Invalid regex: {e}")

        results: list[str] = []
        for root, _dirs, files in self.workdir.rglob("*"):
            if not root.is_dir():
                continue
            # 跳过常见忽略目录
            parts = root.relative_to(self.workdir).parts
            if any(p in {".git", "node_modules", "__pycache__", ".venv", "venv"} for p in parts):
                continue
            for fname in files:
                if glob and not fnmatch.fnmatch(fname, glob):
                    continue
                fpath = root / fname
                try:
                    text = fpath.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                for i, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        rel = fpath.relative_to(self.workdir)
                        results.append(f"{rel}:{i}:{line}")
                        if len(results) >= max_results:
                            return ToolResult(content="\n".join(results))

        if not results:
            return ToolResult(content=f"No matches for: {pattern}")
        return ToolResult(content="\n".join(results))
