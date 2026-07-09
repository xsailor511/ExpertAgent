"""Docker 沙箱 (可选, 需安装 docker 包)。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from coding_agent.sandbox.base import ExecutionResult, Sandbox
from coding_agent.utils.logging import get_logger

log = get_logger(__name__)


class DockerSandbox(Sandbox):
    """Docker 容器沙箱 — 每次执行在临时容器中运行。

    需要安装: pip install coding-agent[sandbox]
    """

    def __init__(self, workdir: Path, image: str = "python:3.12-slim") -> None:
        self.workdir = Path(workdir)
        self.image = image
        try:
            import docker  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "Docker SDK not installed. Run: pip install docker"
            ) from e
        self._client = None

    async def run(
        self,
        command: str,
        timeout: int = 30,
        cwd: Optional[str] = None,
    ) -> ExecutionResult:
        # Docker SDK 是同步的, 这里用 anyio 包装
        import anyio

        return await anyio.to_thread.run_sync(
            self._run_sync, command, timeout, cwd or str(self.workdir)
        )

    def _run_sync(self, command: str, timeout: int, cwd: str) -> ExecutionResult:
        import docker

        if self._client is None:
            self._client = docker.from_env()

        try:
            result = self._client.containers.run(
                self.image,
                command=["sh", "-c", command],
                working_dir="/workspace",
                volumes={str(self.workdir): {"bind": "/workspace", "mode": "rw"}},
                remove=True,
                stdout=True,
                stderr=True,
                detach=False,
                timeout=timeout,
            )
            # result 是 bytes
            if isinstance(result, bytes):
                return ExecutionResult(
                    stdout=result.decode("utf-8", errors="replace"),
                    stderr="",
                    exit_code=0,
                )
            return ExecutionResult(stdout=str(result), stderr="", exit_code=0)
        except Exception as e:
            return ExecutionResult(stdout="", stderr=str(e), exit_code=-1)

    async def close(self) -> None:
        if self._client:
            self._client.close()
