"""Background task execution manager — spawns slow operations in daemon threads."""

from __future__ import annotations

import queue
import subprocess
import threading
import time
from collections.abc import Callable

SLOW_KEYWORDS = [
    "install",
    "build",
    "test",
    "deploy",
    "compile",
    "pip install",
    "npm install",
    "cargo build",
    "make",
    "docker build",
    "composer install",
]


def is_slow(command: str) -> bool:
    """Heuristic: does the command look like a long-running operation?"""
    lower = command.lower()
    return any(kw in lower for kw in SLOW_KEYWORDS)


class BackgroundTask:
    def __init__(self, task_id: str, command: str):
        self.task_id = task_id
        self.command = command
        self.start_time = time.time()
        self._result: str | None = None
        self._error: str | None = None

    @property
    def elapsed(self) -> float:
        return time.time() - self.start_time

    def to_notification(self) -> str:
        elapsed_s = f"{self.elapsed:.1f}s"
        if self._error:
            return (
                f"<task_notification>\n"
                f"  Background task {self.task_id} FAILED after {elapsed_s}:\n"
                f"  Command: {self.command}\n"
                f"  Error: {self._error}\n"
                f"</task_notification>"
            )
        return (
            f"<task_notification>\n"
            f"  Background task {self.task_id} completed in {elapsed_s}:\n"
            f"  Command: {self.command}\n"
            f"  Result:\n{self._result}\n"
            f"</task_notification>"
        )


class BackgroundTaskManager:
    """Manages background execution of slow commands."""

    def __init__(self) -> None:
        self._pending: dict[str, BackgroundTask] = {}
        self._results: queue.Queue[str] = queue.Queue()
        self._counter = 0

    def start(self, command: str, run_fn: Callable[[], str]) -> str:
        """Dispatch a command to a background thread. Returns a placeholder."""
        self._counter += 1
        task_id = f"bg_{self._counter:04d}"
        task = BackgroundTask(task_id, command)
        self._pending[task_id] = task

        def _run() -> None:
            try:
                result = run_fn()
                task._result = result
            except Exception as e:
                task._error = str(e)
            self._results.put(task.to_notification())

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return (
            f"[Background task {task_id} started]\n"
            f"Command: {command}\n"
            f"You'll be notified when it completes. Continue with other work."
        )

    def collect_results(self) -> list[str]:
        """Drain completed results. Call before each LLM iteration."""
        notes: list[str] = []
        while not self._results.empty():
            try:
                notes.append(self._results.get_nowait())
            except queue.Empty:
                break
        return notes

    def is_pending(self, task_id: str) -> bool:
        return task_id in self._pending


def _exec_command(command: str) -> str:
    """Run a bash command synchronously and return output."""
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        error = result.stderr or ""
        raise RuntimeError(f"Exit {result.returncode}: {error[:2000]}")
    return result.stdout[:5000]
