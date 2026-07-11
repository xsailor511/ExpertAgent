from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from coding_agent.llm.base import LLMProvider, LLMResponse, Message
from coding_agent.teams.coordinator import TeamCoordinator
from coding_agent.tools.base import Tool, ToolResult

IDLE_POLL_INTERVAL = 5
IDLE_TIMEOUT = 5


def _input_schema(required: list[str], **props: Any) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


SUB_TOOL_DEFS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": _input_schema(["command"], command={"type": "string"})},
    {"name": "read_file", "description": "Read file.",
     "input_schema": _input_schema(["path"],
         path={"type": "string"}, limit={"type": "integer"}, offset={"type": "integer"})},
    {"name": "write_file", "description": "Write file.",
     "input_schema": _input_schema(["path", "content"],
         path={"type": "string"}, content={"type": "string"})},
    {"name": "edit_file", "description": "Edit file.",
     "input_schema": _input_schema(["path", "old_text", "new_text"],
         path={"type": "string"}, old_text={"type": "string"}, new_text={"type": "string"})},
    {"name": "send_message", "description": "Send message to lead.",
     "input_schema": _input_schema(["content"], content={"type": "string"})},
    {"name": "submit_plan", "description": "Submit a plan for lead approval.",
     "input_schema": _input_schema(["plan"], plan={"type": "string"})},
]


class SpawnTeammateTool(Tool):
    name: ClassVar[str] = "spawn_teammate"
    description: ClassVar[str] = "Spawn an autonomous teammate agent as a background thread."
    requires_confirmation: ClassVar[bool] = True

    class Params(BaseModel):
        name: str = Field(..., description="Unique name for the teammate")
        role: str = Field(..., description="Role description (e.g. 'frontend developer')")
        prompt: str = Field(..., description="Initial task prompt for the teammate")

    def __init__(self, llm: LLMProvider, coordinator: TeamCoordinator, workdir: Path) -> None:
        self.llm = llm
        self.coordinator = coordinator
        self.workdir = Path(workdir)

    async def execute(self, name: str, role: str, prompt: str) -> ToolResult:
        if self.coordinator.is_teammate_active(name):
            return ToolResult(content=f"Teammate '{name}' already exists", is_error=True)

        llm = self.llm
        coordinator = self.coordinator
        workdir = self.workdir

        def _run():
            messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
            sub_handlers: dict[str, Any] = {
                "bash": lambda cmd, _w=workdir: _exec_bash(cmd, _w),
                "read_file": lambda path, limit=None, offset=0, _w=workdir: _exec_read(
                    path, limit, offset, _w
                ),
                "write_file": lambda path, content, _w=workdir: _exec_write(path, content, _w),
                "edit_file": lambda path, old_text, new_text, _w=workdir: _exec_edit(
                    path, old_text, new_text, _w
                ),
                "send_message": lambda content: (
                    coordinator.bus.send(
                        "lead", {"type": "message", "from": name, "content": content}
                    ),
                    "Sent",
                )[1],
                "submit_plan": lambda plan: _submit_plan(name, plan, coordinator),
            }
            waiting_plan: str | None = None

            while True:
                if _check_shutdown(coordinator, name, messages, waiting_plan, lambda: None):
                    break

                if waiting_plan:
                    time.sleep(IDLE_POLL_INTERVAL)
                    continue

                def _llm_call():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    msg_objects = []
                    for m in messages[-20:]:
                        msg_objects.append(Message(
                            role=m["role"],
                            content=m.get("content", ""),
                            tool_calls=m.get("tool_calls"),
                        ))
                    resp = loop.run_until_complete(
                        llm.chat(messages=msg_objects, tools=SUB_TOOL_DEFS)
                    )
                    loop.close()
                    return resp

                try:
                    response = _llm_call()
                except Exception:
                    break

                tool_calls = _get_tool_calls(response)
                if not tool_calls:
                    break

                content = response.content or "" if isinstance(response, LLMResponse) else ""
                msgs_content = []
                for tc in tool_calls:
                    handler = sub_handlers.get(tc.name)
                    if handler:
                        try:
                            output = handler(**tc.arguments)
                        except Exception as e:
                            output = f"Error: {e}"
                    else:
                        output = f"Unknown tool: {tc.name}"
                    msgs_content.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": str(output),
                    })
                    if tc.name == "submit_plan":
                        match = re.search(r"\((req_\d+)\)", str(output))
                        if match:
                            waiting_plan = match.group(1)

                messages.append({
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                        for tc in tool_calls
                    ],
                })
                messages.append({"role": "user", "content": msgs_content})

                if waiting_plan:
                    continue

                # Idle poll for tasks
                if _idle_poll(coordinator, name, messages):
                    break

            coordinator.bus.send("lead", {
                "type": "result", "from": name, "content": "Teammate finished.",
            })
            coordinator.unregister_teammate(name)

        coordinator.register_teammate(name)
        threading.Thread(target=_run, daemon=True).start()
        return ToolResult(content=f"Teammate '{name}' spawned as {role}")


def _check_shutdown(
    coordinator: TeamCoordinator, name: str, messages: list,
    waiting_plan: str | None, _after: Any,
) -> bool:
    inbox = coordinator.bus.read(name)
    for msg in inbox:
        if msg.get("type") == "shutdown_request":
            coordinator.bus.send("lead", {
                "type": "shutdown_response", "from": name,
                "request_id": msg.get("request_id", ""),
            })
            return True
        if (msg.get("type") == "plan_approval_response"
                and waiting_plan
                and msg.get("request_id") == waiting_plan):
            waiting_plan = None
            status = "approved" if msg.get("approve") else "rejected"
            messages.append({
                "role": "user",
                "content": f"[Plan {status}] {msg.get('content', '')}",
            })
    return False


def _idle_poll(coordinator: TeamCoordinator, name: str, messages: list) -> bool:
    for _ in range(IDLE_TIMEOUT):
        time.sleep(IDLE_POLL_INTERVAL)
        inbox = coordinator.bus.read(name)
        if inbox:
            for msg in inbox:
                if msg.get("type") == "shutdown_request":
                    return True
                messages.append({
                    "role": "user",
                    "content": f"<inbox>{json.dumps(inbox)}</inbox>",
                })
            return False
    return False


def _get_tool_calls(response: Any) -> list:
    if isinstance(response, LLMResponse):
        return response.tool_calls or []
    content = getattr(response, "content", [])
    if not isinstance(content, list):
        return []
    tool_calls = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tc = type("ToolCall", (), {"id": None, "name": None, "arguments": {}})()
            tc.id = block.get("id", block.get("tool_use_id", ""))
            tc.name = block.get("name", "")
            tc.arguments = block.get("input", {})
            tool_calls.append(tc)
        elif hasattr(block, "type") and block.type == "tool_use":
            tool_calls.append(block)
    return tool_calls


class SendMessageTool(Tool):
    name: ClassVar[str] = "send_message"
    description: ClassVar[str] = "Send a message to a teammate."
    requires_confirmation: ClassVar[bool] = False

    class Params(BaseModel):
        to: str = Field(..., description="Recipient teammate name")
        content: str = Field(..., description="Message content")

    def __init__(self, coordinator: TeamCoordinator) -> None:
        self.coordinator = coordinator

    async def execute(self, to: str, content: str) -> ToolResult:
        self.coordinator.bus.send(to, {
            "type": "message", "from": "lead", "content": content,
        })
        return ToolResult(content=f"Sent to {to}")


class CheckInboxTool(Tool):
    name: ClassVar[str] = "check_inbox"
    description: ClassVar[str] = "Check inbox for messages and protocol responses."
    requires_confirmation: ClassVar[bool] = False

    class Params(BaseModel):
        pass

    def __init__(self, coordinator: TeamCoordinator) -> None:
        self.coordinator = coordinator

    async def execute(self) -> ToolResult:
        msgs = self.coordinator.consume_lead_inbox()
        if not msgs:
            return ToolResult(content="(inbox empty)")
        lines = []
        for m in msgs:
            req_id = m.get("request_id", "")
            tag = f" [{m.get('type', 'message')}]"
            if req_id:
                tag += f" req:{req_id}"
            fr = m.get("from", "?")
            content = m.get("content", "")[:200]
            lines.append(f"  [{fr}]{tag} {content}")
        return ToolResult(content="\n".join(lines))


# --- Helpers ---

def _exec_bash(command: str, workdir: Path) -> str:
    import subprocess
    try:
        r = subprocess.run(
            command, shell=True, cwd=workdir,
            capture_output=True, text=True, timeout=120,
        )
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except Exception as e:
        return f"Error: {e}"


def _exec_read(path: str, limit: int | None, offset: int, workdir: Path) -> str:
    try:
        fp = (workdir / path).resolve()
        if not fp.is_relative_to(workdir):
            return f"Error: path escapes workspace: {path}"
        lines = fp.read_text().splitlines()
        off = max(int(offset or 0), 0)
        lim = int(limit) if limit is not None else None
        lines = lines[off:]
        if lim is not None and lim < len(lines):
            lines = lines[:lim] + [f"... ({len(lines) - lim} more lines)"]
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def _exec_write(path: str, content: str, workdir: Path) -> str:
    try:
        fp = (workdir / path).resolve()
        if not fp.is_relative_to(workdir):
            return f"Error: path escapes workspace: {path}"
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def _exec_edit(path: str, old_text: str, new_text: str, workdir: Path) -> str:
    try:
        fp = (workdir / path).resolve()
        if not fp.is_relative_to(workdir):
            return f"Error: path escapes workspace: {path}"
        text = fp.read_text()
        if old_text not in text:
            return f"Error: text not found in {path}"
        fp.write_text(text.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


def _submit_plan(from_name: str, plan: str, coordinator: TeamCoordinator) -> str:
    import random
    req_id = f"req_{int(time.time() * 1000)}_{random.randint(0, 9999):04d}"
    coordinator.register_pending_plan(req_id, from_name, plan)
    coordinator.bus.send("lead", {
        "type": "plan_approval_request",
        "from": from_name,
        "request_id": req_id,
        "content": plan,
    })
    return f"Plan submitted ({req_id})"
