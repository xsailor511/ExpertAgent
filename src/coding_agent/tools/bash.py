"""Bash 命令执行工具。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from coding_agent.tools.base import Tool, ToolError, ToolResult


class BashTool(Tool):
    """执行 shell 命令。"""

    name: ClassVar[str] = "bash"
    description: ClassVar[str] = (
        "在工作目录中执行 shell 命令并返回 stdout/stderr。"
        "命令有 30 秒超时。参数: command (命令字符串), timeout (超时秒数, 可选)"
    )
    requires_confirmation: ClassVar[bool] = True

    class Params(BaseModel):
        command: str = Field(..., description="要执行的 shell 命令")
        timeout: int = Field(30, ge=1, le=300, description="超时秒数")

    def __init__(self, workdir: Path) -> None:
        self.workdir = Path(workdir)

    async def execute(
        self, command: str, timeout: int = 30, **kwargs: Any
    ) -> ToolResult:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workdir),
            )
        except Exception as e:
            raise ToolError(f"Failed to start command: {e}", recoverable=False)

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise ToolError(
                f"Command timed out after {timeout}s: {command}", recoverable=True
            )

        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")

        parts = []
        if stdout_text:
            parts.append(f"stdout:\n{stdout_text}")
        if stderr_text:
            parts.append(f"stderr:\n{stderr_text}")
        parts.append(f"exit_code: {proc.returncode}")

        is_error = proc.returncode != 0
        return ToolResult(
            content="\n".join(parts) if parts else "(no output)",
            is_error=is_error,
            metadata={"exit_code": proc.returncode, "command": command},
        )
