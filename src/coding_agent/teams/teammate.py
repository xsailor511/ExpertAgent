"""Teammate — a daemon thread running an independent LLM loop."""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from typing import Any

from coding_agent.llm.base import LLMProvider, LLMResponse, Message
from coding_agent.tasks.graph import TaskGraph
from coding_agent.tasks.store import TaskStore
from coding_agent.teams.bus import MessageBus
from coding_agent.teams.protocol import ProtocolState
from coding_agent.tools.base import ToolResult
from coding_agent.tools.registry import ToolRegistry
from coding_agent.utils.logging import get_logger

log = get_logger(__name__)

TEAMMATE_PROMPT = """\
You are a teammate agent in a multi-agent coding system.

Your role: assist the lead agent by completing tasks assigned via the task system.

Rules:
1. You can use tools (bash, read_file, write_file, edit_file, search) to complete work.
2. Check for new tasks via list_tasks and claim_task.
3. Communicate progress via the message bus.
4. Never spawn other agents.
5. Keep responses concise and focused on task completion.

Your agent_id: {agent_id}
"""


class Teammate:
    """A daemon thread running an independent agent loop."""

    def __init__(
        self,
        agent_id: str,
        llm: LLMProvider,
        tools: ToolRegistry,
        task_store: TaskStore,
        task_graph: TaskGraph,
        bus: MessageBus,
        idle_poll_interval: float = 5.0,
    ) -> None:
        self.agent_id = agent_id
        self.llm = llm
        self.tools = tools
        self.task_store = task_store
        self.task_graph = task_graph
        self.bus = bus
        self.protocol = ProtocolState(agent_id, bus)
        self.idle_poll_interval = idle_poll_interval
        self._running = False
        self._thread: threading.Thread | None = None
        self._wake_event = threading.Event()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._wake_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        log.info(f"Teammate '{self.agent_id}' started")

    def stop(self) -> None:
        self._running = False
        self._wake_event.set()
        log.info(f"Teammate '{self.agent_id}' stopped")

    def _run_loop(self) -> None:
        """Main loop: poll inbox, check for tasks, work on claims."""
        while self._running:
            try:
                self._process_inbox()
                self._try_claim_task()
            except Exception:
                log.exception(f"Teammate '{self.agent_id}' loop error")
            self._wake_event.wait(self.idle_poll_interval)
            self._wake_event.clear()

    def _process_inbox(self) -> None:
        """Check messages and handle shutdown requests."""
        actions = self.protocol.consume_inbox()
        for action in actions:
            if action["type"] == "shutdown_request":
                log.info(
                    f"Teammate '{self.agent_id}' received shutdown: "
                    f"{action.get('reason', '')}"
                )
                self._running = False
                return

    def _try_claim_task(self) -> None:
        """Look for claimable tasks and work on one."""
        claimable = self.task_graph.claimable()
        if not claimable:
            return

        task = claimable[0]
        task.owner = self.agent_id
        task.status = "in_progress"
        self.task_store.save(task)

        log.info(f"Teammate '{self.agent_id}' claimed task: {task.subject}")

        if self.llm is None or self.tools is None:
            return

        try:
            self._work_on_task(task.subject)
            task.status = "completed"
            self.task_store.save(task)
            log.info(f"Teammate '{self.agent_id}' completed task: {task.subject}")
        except Exception:
            log.exception(f"Teammate '{self.agent_id}' failed task: {task.subject}")
            task.status = "pending"
            task.owner = None
            self.task_store.save(task)

    def _work_on_task(self, prompt: str) -> str:
        """Execute one LLM call session to work on a task."""
        messages: list[Any] = [
            {"role": "system", "content": TEAMMATE_PROMPT.format(agent_id=self.agent_id)},
            {"role": "user", "content": prompt},
        ]
        tool_schemas = self.tools.schemas()
        max_iterations = 10
        final = ""

        for _ in range(max_iterations):
            msg_objects: list[Any] = []
            for m in messages:
                if isinstance(m, dict):
                    msg_objects.append(Message(
                        role=m["role"],
                        content=m.get("content", ""),
                        tool_calls=m.get("tool_calls"),
                    ))
                else:
                    msg_objects.append(m)
            messages = msg_objects

            try:
                response = self.llm.chat(messages=messages, tools=tool_schemas)
                coro = response
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop and loop.is_running():
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        response = pool.submit(asyncio.run, coro).result()
                else:
                    response = asyncio.run(coro)
            except Exception as e:
                log.error(f"Teammate LLM error: {e}")
                final = f"Error: {e}"
                break

            if isinstance(response, LLMResponse):
                content = response.content or ""
                tool_calls_data = response.tool_calls or []
            else:
                content = getattr(response, "content", "") or ""
                tool_calls_data = getattr(response, "tool_calls", []) or []

            if not tool_calls_data:
                final = content
                break

            messages.append(Message(
                role="assistant",
                content=content,
                tool_calls=tool_calls_data,
            ))

            for tc in tool_calls_data:
                tc_name = tc.name if hasattr(tc, "name") else tc.get("name", "")
                tc_args = tc.arguments if hasattr(tc, "arguments") else tc.get("arguments", {})
                tc_id = tc.id if hasattr(tc, "id") else tc.get("id", "")

                try:
                    result = self.tools.execute(tc_name, tc_args, approved=True)
                    coro = result
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = None
                    if loop and loop.is_running():
                        with concurrent.futures.ThreadPoolExecutor() as pool:
                            result = pool.submit(asyncio.run, coro).result()
                    else:
                        result = asyncio.run(coro)
                except Exception as e:
                    result = ToolResult(content=f"Error: {e}", is_error=True)

                messages.append(Message(
                    role="tool",
                    content=result.content if hasattr(result, "content") else str(result),
                    tool_call_id=tc_id,
                    name=tc_name,
                ))

        return final or "(no output)"
