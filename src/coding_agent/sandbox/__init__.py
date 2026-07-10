"""Execution sandboxes."""

from coding_agent.sandbox.base import ExecutionResult, Sandbox
from coding_agent.sandbox.local import LocalSandbox

try:
    from coding_agent.sandbox.e2b import E2BSandbox
except ImportError:
    E2BSandbox = None  # type: ignore[assignment]

__all__ = [
    "ExecutionResult",
    "Sandbox",
    "LocalSandbox",
    "E2BSandbox",
]
