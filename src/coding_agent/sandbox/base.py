"""沙箱抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ExecutionResult:
    """命令执行结果。"""

    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False


class Sandbox(ABC):
    """执行沙箱抽象基类。"""

    @abstractmethod
    async def run(
        self,
        command: str,
        timeout: int = 30,
        cwd: str | None = None,
    ) -> ExecutionResult:
        """在沙箱中执行命令。"""
        ...

    @abstractmethod
    async def close(self) -> None:
        """释放资源。"""
        ...
