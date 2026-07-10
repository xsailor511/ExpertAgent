"""E2B cloud sandbox implementation."""

from __future__ import annotations

import asyncio

from coding_agent.sandbox.base import ExecutionResult, Sandbox
from coding_agent.utils.logging import get_logger

log = get_logger(__name__)

try:
    from e2b_code_interpreter import Sandbox as E2BSandbox

    HAS_E2B = True
except ImportError:
    HAS_E2B = False


class E2BSandbox(Sandbox):
    """E2B Code Interpreter cloud sandbox.

    Requires:
        - pip install e2b-code-interpreter
        - E2B_API_KEY environment variable
    """

    def __init__(self, api_key: str | None = None) -> None:
        if not HAS_E2B:
            raise ImportError(
                "e2b-code-interpreter is not installed. "
                "Install with: pip install e2b-code-interpreter"
            )
        self.api_key = api_key
        self._sandbox: E2BSandbox | None = None

    async def run(
        self,
        command: str,
        timeout: int = 30,
        cwd: str | None = None,
    ) -> ExecutionResult:
        if self._sandbox is None:
            self._sandbox = await self._create()

        try:
            result = await asyncio.wait_for(
                self._sandbox.run_code(command),
                timeout=timeout,
            )
        except TimeoutError:
            return ExecutionResult(
                stdout="",
                stderr="Command timed out",
                exit_code=-1,
                timed_out=True,
            )
        except Exception as e:
            return ExecutionResult(
                stdout="",
                stderr=str(e),
                exit_code=1,
            )

        return ExecutionResult(
            stdout=result.text or "",
            stderr=result.error or "",
            exit_code=0 if not result.error else 1,
        )

    async def close(self) -> None:
        if self._sandbox is not None:
            try:
                self._sandbox.kill()
            except Exception:
                log.warning("Error closing E2B sandbox", exc_info=True)
            self._sandbox = None

    async def _create(self) -> E2BSandbox:
        """Create a new E2B sandbox session."""
        kwargs = {}
        if self.api_key:
            kwargs["api_key"] = self.api_key
        loop = asyncio.get_running_loop()
        sandbox = await loop.run_in_executor(
            None,
            lambda: E2BSandbox(**kwargs),
        )
        return sandbox
