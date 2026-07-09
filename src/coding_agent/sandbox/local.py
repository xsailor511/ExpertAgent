"""本地 subprocess 沙箱。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from coding_agent.sandbox.base import ExecutionResult, Sandbox
from coding_agent.utils.logging import get_logger

log = get_logger(__name__)


class LocalSandbox(Sandbox):
    """本地 subprocess 执行沙箱 (无隔离)。"""

    def __init__(self, workdir: Path) -> None:
        self.workdir = Path(workdir)

    async def run(
        self,
        command: str,
        timeout: int = 30,
        cwd: Optional[str] = None,
    ) -> ExecutionResult:
        work_dir = Path(cwd) if cwd else self.workdir
        log.debug(f"LocalSandbox run: {command} (cwd={work_dir})")

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(work_dir),
            )
        except Exception as e:
            return ExecutionResult(stdout="", stderr=str(e), exit_code=-1)

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return ExecutionResult(
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                exit_code=proc.returncode or 0,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ExecutionResult(
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                exit_code=-1,
                timed_out=True,
            )

    async def close(self) -> None:
        pass
