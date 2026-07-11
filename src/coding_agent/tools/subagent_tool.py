from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from coding_agent.llm.base import LLMProvider, LLMResponse, Message
from coding_agent.tools.base import Tool, ToolResult


class SubagentTool(Tool):
    name: ClassVar[str] = "task"
    description: ClassVar[str] = (
        "Launch a focused subagent. Returns only its final summary. "
        "Use for isolated research, exploration, or implementation tasks."
    )

    class Params(BaseModel):
        description: str = Field(..., description="Task description for the subagent")

    def __init__(self, llm: LLMProvider, workdir: Path) -> None:
        self.llm = llm
        self.workdir = Path(workdir)

    async def execute(self, description: str) -> ToolResult:
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    f"You are a coding subagent at {self.workdir}. "
                    "Complete the task, then return a concise final summary. "
                    "Do not spawn more agents."
                ),
            },
            {"role": "user", "content": description},
        ]
        sub_tools = [
            {
                "name": "bash",
                "description": "Run a shell command.",
                "input_schema": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            },
            {
                "name": "read_file",
                "description": "Read file contents.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "limit": {"type": "integer"},
                        "offset": {"type": "integer"},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "write_file",
                "description": "Write content to a file.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "edit_file",
                "description": "Replace exact text in a file once.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "old_text": {"type": "string"},
                        "new_text": {"type": "string"},
                    },
                    "required": ["path", "old_text", "new_text"],
                },
            },
            {
                "name": "glob",
                "description": "Find files matching a glob pattern.",
                "input_schema": {
                    "type": "object",
                    "properties": {"pattern": {"type": "string"}},
                    "required": ["pattern"],
                },
            },
        ]
        sub_handlers: dict[str, Any] = {
            "bash": self._run_bash,
            "read_file": self._run_read,
            "write_file": self._run_write,
            "edit_file": self._run_edit,
            "glob": self._run_glob,
        }

        max_iterations = 30
        for _ in range(max_iterations):
            # Convert to Message objects for LLM call
            msg_objects = []
            for m in messages:
                if isinstance(m, dict):
                    msg_objects.append(Message(
                        role=m["role"],
                        content=m.get("content", ""),
                        tool_calls=m.get("tool_calls"),
                    ))
                else:
                    msg_objects.append(m)

            response = await self.llm.chat(messages=msg_objects, tools=sub_tools)
            if not isinstance(response, LLMResponse):
                break

            content = response.content or ""
            tool_calls = response.tool_calls or []

            if not tool_calls:
                return ToolResult(content=content or "(no output)")

            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                    for tc in tool_calls
                ],
            })

            for tc in tool_calls:
                handler = sub_handlers.get(tc.name)
                if handler:
                    try:
                        result = handler(**tc.arguments)
                    except Exception as e:
                        result = str(e)
                else:
                    result = f"Unknown tool: {tc.name}"
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                    "name": tc.name,
                })

        return ToolResult(content="Subagent finished without a text summary.")

    def _run_bash(self, command: str) -> str:
        import subprocess
        try:
            r = subprocess.run(
                command, shell=True, cwd=self.workdir,
                capture_output=True, text=True, timeout=120,
            )
            out = (r.stdout + r.stderr).strip()
            return out[:50000] if out else "(no output)"
        except subprocess.TimeoutExpired:
            return "Error: Timeout (120s)"
        except Exception as e:
            return f"Error: {e}"

    def _run_read(self, path: str, limit: int | None = None, offset: int = 0) -> str:
        try:
            fp = (self.workdir / path).resolve()
            if not fp.is_relative_to(self.workdir):
                return f"Error: path escapes workspace: {path}"
            lines = fp.read_text().splitlines()
            offset = max(int(offset or 0), 0)
            limit_val = int(limit) if limit is not None else None
            lines = lines[offset:]
            if limit_val is not None and limit_val < len(lines):
                lines = lines[:limit_val] + [f"... ({len(lines) - limit_val} more lines)"]
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    def _run_write(self, path: str, content: str) -> str:
        try:
            fp = (self.workdir / path).resolve()
            if not fp.is_relative_to(self.workdir):
                return f"Error: path escapes workspace: {path}"
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content)
            return f"Wrote {len(content)} bytes to {path}"
        except Exception as e:
            return f"Error: {e}"

    def _run_edit(self, path: str, old_text: str, new_text: str) -> str:
        try:
            fp = (self.workdir / path).resolve()
            if not fp.is_relative_to(self.workdir):
                return f"Error: path escapes workspace: {path}"
            text = fp.read_text()
            if old_text not in text:
                return f"Error: text not found in {path}"
            fp.write_text(text.replace(old_text, new_text, 1))
            return f"Edited {path}"
        except Exception as e:
            return f"Error: {e}"

    def _run_glob(self, pattern: str) -> str:
        import glob as g
        try:
            results = []
            for match in g.glob(pattern, root_dir=self.workdir):
                if (self.workdir / match).resolve().is_relative_to(self.workdir):
                    results.append(match)
            return "\n".join(results) if results else "(no matches)"
        except Exception as e:
            return f"Error: {e}"
