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
from coding_agent.ui.terminal import TerminalUI
from coding_agent.utils.logging import get_logger

log = get_logger(__name__)

IDLE_POLL_INTERVAL = 5
IDLE_TIMEOUT = 5


def _input_schema(required: list[str], **props: Any) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


SUB_TOOL_DEFS = [
    {"type": "function", "function": {
        "name": "bash", "description": "Run a shell command.",
        "parameters": _input_schema(["command"], command={"type": "string"})}},
    {"type": "function", "function": {
        "name": "read_file", "description": "Read file.",
        "parameters": _input_schema(["path"],
            path={"type": "string"}, limit={"type": "integer"}, offset={"type": "integer"})}},
    {"type": "function", "function": {
        "name": "write_file", "description": "Write file.",
        "parameters": _input_schema(["path", "content"],
            path={"type": "string"}, content={"type": "string"})}},
    {"type": "function", "function": {
        "name": "edit_file", "description": "Edit file.",
        "parameters": _input_schema(["path", "old_text", "new_text"],
            path={"type": "string"}, old_text={"type": "string"}, new_text={"type": "string"})}},
    {"type": "function", "function": {
        "name": "send_message", "description": "Send message to lead.",
        "parameters": _input_schema(["content"], content={"type": "string"})}},
    {"type": "function", "function": {
        "name": "submit_plan", "description": "Submit a plan for lead approval.",
        "parameters": _input_schema(["plan"], plan={"type": "string"})}},
]


class SpawnTeammateTool(Tool):
    name: ClassVar[str] = "spawn_teammate"
    description: ClassVar[str] = "Spawn an autonomous teammate agent as a background thread."
    requires_confirmation: ClassVar[bool] = True

    class Params(BaseModel):
        name: str = Field(..., description="Unique name for the teammate")
        role: str = Field(..., description="Role description (e.g. 'frontend developer')")
        prompt: str = Field(..., description="Initial task prompt for the teammate")

    def __init__(
        self, llm: LLMProvider, coordinator: TeamCoordinator, workdir: Path,
        ui: TerminalUI | None = None,
    ) -> None:
        self.llm = llm
        self.coordinator = coordinator
        self.workdir = Path(workdir)
        self.ui = ui

    def set_ui(self, ui: TerminalUI) -> None:
        self.ui = ui

    async def execute(self, name: str, role: str, prompt: str) -> ToolResult:
        if self.coordinator.is_teammate_active(name):
            return ToolResult(content=f"Teammate '{name}' already exists", is_error=True)

        llm = self.llm
        coordinator = self.coordinator
        workdir = self.workdir
        ui = self.ui

        if ui:
            ui.print_teammate_progress(name, f"开始工作: {prompt[:80]}...")

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
                should_break, waiting_plan = _check_shutdown(
                    coordinator, name, messages, waiting_plan, lambda: None,
                )
                if should_break:
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
                except Exception as e:
                    log.error("Teammate '%s' LLM call failed: %s", name, e)
                    if ui:
                        ui.print_teammate_progress(name, f"LLM 调用失败: {e}")
                    coordinator.bus.send("lead", {
                        "type": "result", "from": name,
                        "content": f"[队友 {name} 执行失败] LLM 调用异常: {e}",
                    })
                    coordinator.unregister_teammate(name)
                    return

                tool_calls = _get_tool_calls(response)
                if not tool_calls:
                    log.info("Teammate '%s' finished (no tool calls)", name)
                    break

                content = response.content or "" if isinstance(response, LLMResponse) else ""

                tool_outputs: list[tuple[str, str, str]] = []
                for tc in tool_calls:
                    handler = sub_handlers.get(tc.name)
                    if handler:
                        try:
                            output = handler(**tc.arguments)
                        except Exception as e:
                            output = f"Error: {e}"
                    else:
                        output = f"Unknown tool: {tc.name}"
                    tool_outputs.append((tc.id, tc.name, str(output)))
                    if tc.name == "submit_plan":
                        match = re.search(r"\((req_\d+)\)", str(output))
                        if match:
                            waiting_plan = match.group(1)
                            if ui:
                                ui.print_teammate_progress(
                                    name, f"提交计划审阅: {match.group(1)}"
                                )
                    elif tc.name == "bash" and ui:
                        brief = tc.arguments.get("command", "")[:60]
                        ui.print_teammate_progress(name, f"bash: {brief}")
                    elif tc.name == "write_file" and ui:
                        brief = tc.arguments.get("path", "")
                        ui.print_teammate_progress(name, f"写入文件: {brief}")

                messages.append({
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                        for tc in tool_calls
                    ],
                })
                for tc_id, tc_name, tc_output in tool_outputs:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": tc_output,
                        "name": tc_name,
                    })

                if waiting_plan:
                    continue

                if _idle_poll(coordinator, name, messages):
                    log.info("Teammate '%s' idle timeout", name)
                    coordinator.bus.send("lead", {
                        "type": "result", "from": name,
                        "content": f"[队友 {name} 执行超时] 长时间无新消息，已自行结束。",
                    })
                    coordinator.unregister_teammate(name)
                    return

            # Capture last assistant message as result
            result_content = "Teammate finished."
            for m in reversed(messages):
                if m.get("role") == "assistant" and m.get("content"):
                    result_content = m["content"]
                    break
            # Send result to lead's inbox (consumed by the lead's loop)
            log.info("队友 '%s' 发送结果到 lead 邮箱 (%d 字符)", name, len(result_content))
            coordinator.bus.send("lead", {
                "type": "result", "from": name, "content": result_content,
            })
            coordinator.unregister_teammate(name)
            if ui:
                ui.print_teammate_complete(name, result_content[:200])

        coordinator.register_teammate(name)
        threading.Thread(target=_run, daemon=True).start()
        return ToolResult(
            content=f"Teammate '{name}' spawned as {role} — 任务已随创建参数传入，无需再发送消息。"
        )


def _check_shutdown(
    coordinator: TeamCoordinator, name: str, messages: list,
    waiting_plan: str | None, _after: Any,
) -> tuple[bool, str | None]:
    inbox = coordinator.bus.read(name)
    for msg in inbox:
        if msg.get("type") == "shutdown_request":
            coordinator.bus.send("lead", {
                "type": "shutdown_response", "from": name,
                "request_id": msg.get("request_id", ""),
            })
            return True, waiting_plan
        if (msg.get("type") == "plan_approval_response"
                and waiting_plan
                and msg.get("request_id") == waiting_plan):
            status = "approved" if msg.get("approve") else "rejected"
            messages.append({
                "role": "user",
                "content": f"[Plan {status}] {msg.get('content', '')}",
            })
            return False, None
    return False, waiting_plan


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
