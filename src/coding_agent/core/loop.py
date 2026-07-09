"""ReAct 推理-行动循环。"""

from __future__ import annotations

import json
from typing import Any

from coding_agent.llm.base import LLMProvider, Message, StreamChunk
from coding_agent.llm.streaming import StreamAggregator
from coding_agent.permissions.policy import PermissionPolicy
from coding_agent.tools.registry import ToolRegistry
from coding_agent.ui.terminal import TerminalUI
from coding_agent.utils.logging import get_logger

log = get_logger(__name__)

# 单轮对话内最大工具调用次数 (防止死循环)
MAX_TOOL_ITERATIONS = 25


class AgentLoop:
    """ReAct 循环: 思考 → 行动 → 观察 → 再思考。"""

    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry,
        memory: Any,  # Memory 实例
        ui: TerminalUI,
        permissions: PermissionPolicy,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.memory = memory
        self.ui = ui
        self.permissions = permissions

    async def run(self, user_input: str) -> str:
        """执行一轮完整对话。"""
        # 加入用户消息
        self.memory.add_user(user_input)

        tool_schemas = self.tools.schemas()
        final_response = ""

        for iteration in range(MAX_TOOL_ITERATIONS):
            # 流式调用 LLM
            aggregator = StreamAggregator()
            self.ui.start_assistant_stream()

            async for chunk in self.llm.stream(
                messages=self.memory.messages,
                tools=tool_schemas,
            ):
                if chunk.content:
                    self.ui.update_assistant_stream(chunk.content)
                aggregator.add(chunk)

            response = aggregator.finalize()
            self.ui.end_assistant_stream()

            # 记录 assistant 消息 (含 tool_calls)
            self.memory.add_assistant(
                content=response.content,
                tool_calls=[
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in response.tool_calls
                ],
            )

            # 如果没有工具调用, 说明 LLM 给出了最终回答
            if not response.tool_calls:
                final_response = response.content
                break

            # 执行工具调用
            for tc in response.tool_calls:
                await self._execute_tool_call(tc)

        else:
            # 超过最大迭代
            final_response = "Reached maximum tool iterations without final answer."
            self.ui.print_warning(final_response)

        return final_response

    async def _execute_tool_call(self, tc: Any) -> None:
        """执行单个工具调用。"""
        tool = self.tools.get(tc.name)
        if tool is None:
            result_text = f"Error: unknown tool '{tc.name}'"
            self.ui.print_tool_error(tc.name, tc.arguments, result_text)
            self.memory.add_tool(tc.id, tc.name, result_text)
            return

        # 权限检查
        approved = True
        if tool.requires_confirmation:
            approved = await self.permissions.check(
                tool_name=tc.name,
                arguments=tc.arguments,
                description=tool.description,
            )

        if not approved:
            result_text = f"Tool call '{tc.name}' was rejected by user"
            self.ui.print_tool_rejected(tc.name, tc.arguments)
            self.memory.add_tool(tc.id, tc.name, result_text)
            return

        # 显示工具调用
        self.ui.print_tool_call(tc.name, tc.arguments)

        # 执行
        result = await self.tools.execute(tc.name, tc.arguments, approved=approved)

        # 显示结果
        self.ui.print_tool_result(tc.name, result.content, is_error=result.is_error)

        # 记录到 memory
        self.memory.add_tool(tc.id, tc.name, result.content)
