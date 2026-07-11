"""ReAct 推理-行动循环。"""

from __future__ import annotations

import json
from typing import Any

from coding_agent.core.background import BackgroundTaskManager, _exec_command, is_slow
from coding_agent.core.compaction import estimate_size, micro_compact, snip_compact, summary_compact
from coding_agent.core.cron import CronScheduler
from coding_agent.core.hooks import HookEvent, HookRegistry
from coding_agent.core.recovery import RecoveryState, with_retry
from coding_agent.llm.base import LLMProvider, LLMResponse
from coding_agent.llm.streaming import StreamAggregator
from coding_agent.permissions.policy import PermissionPolicy
from coding_agent.tools.mcp.pool import ToolPool
from coding_agent.tools.registry import ToolRegistry
from coding_agent.ui.terminal import TerminalUI
from coding_agent.utils.logging import get_logger

log = get_logger(__name__)

# 单轮对话内最大工具调用次数 (防止死循环)
MAX_TOOL_ITERATIONS = 25
TODO_REMINDER_INTERVAL = 3  # 每 N 轮提醒更新 todo


class AgentLoop:
    """ReAct 循环: 思考 → 行动 → 观察 → 再思考。

    完整 harness，包含:
        - cron / background 通知注入
        - 每轮 context compact + system prompt 刷新
        - todo_write 跟踪与提醒
        - compact 工具拦截 (history summarization)
        - 慢 bash 后台 dispatch
        - hooks + permission 管线
        - ToolPool (内置 + MCP 工具)
    """

    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry | ToolPool,
        memory: Any,  # Memory 实例
        ui: TerminalUI,
        permissions: PermissionPolicy,
        hooks: HookRegistry | None = None,
        recovery_state: RecoveryState | None = None,
        default_max_tokens: int = 8000,
        escalated_max_tokens: int = 16000,
        bg_manager: BackgroundTaskManager | None = None,
        cron_scheduler: CronScheduler | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.memory = memory
        self.ui = ui
        self.permissions = permissions
        self.hooks = hooks or HookRegistry()
        self.recovery_state = recovery_state or RecoveryState(primary="")
        self.default_max_tokens = default_max_tokens
        self.escalated_max_tokens = escalated_max_tokens
        self.bg_manager = bg_manager
        self.cron = cron_scheduler

    async def run(self, user_input: str) -> str:
        """执行一轮完整对话。"""
        # 1. Hook: USER_PROMPT_SUBMIT
        await self.hooks.trigger(
            HookEvent.USER_PROMPT_SUBMIT, user_input=user_input
        )

        # 2. 加入用户消息
        self.memory.add_user(user_input)

        max_tokens = self.default_max_tokens
        final_response = ""
        rounds_since_todo = 0

        for _iteration in range(MAX_TOOL_ITERATIONS):
            # === Pre-LLM: inject scheduled / background / reminders ===

            # Cron queue injection
            if self.cron:
                for prompt in self.cron.pop_fired():
                    msg = f"[Cron] {prompt}"
                    self.memory.add_user(msg)
                    self.ui.print_user(msg)
                    log.info(f"[cron inject] {prompt[:60]}")

            # Background notifications
            if self.bg_manager:
                for note in self.bg_manager.collect_results():
                    self.memory.add_user(note)

            # Todo reminder
            if rounds_since_todo >= TODO_REMINDER_INTERVAL:
                self.memory.add_user("<reminder>更新你的 todo list (使用 todo_write)。</reminder>")
                rounds_since_todo = 0

            # === Context preparation ===

            # 3. 压缩管道
            self.memory.messages = snip_compact(self.memory.messages)
            self.memory.messages = micro_compact(self.memory.messages)
            if estimate_size(self.memory.messages) > self.memory.max_tokens:
                pass  # summary_compact in compact tool only

            # 4. 刷新 system prompt (skills, MCP, time 等)
            self.memory.refresh_system_prompt()

            # 5. 获取最新 tool schemas (包括新连接的 MCP 工具)
            tool_schemas = self.tools.schemas()

            # === LLM call ===

            # 6. 流式调用 LLM (带重试和 max_tokens 升级)
            self.ui.start_assistant_stream()
            _schemas = tool_schemas

            async def _stream(
                _max_tokens: int = max_tokens, _schemas_guard: Any = _schemas
            ) -> LLMResponse:
                agg = StreamAggregator()
                async for chunk in self.llm.stream(
                    messages=self.memory.messages,
                    tools=_schemas_guard,
                    max_tokens=_max_tokens,
                ):
                    if chunk.content:
                        self.ui.update_assistant_stream(chunk.content)
                    agg.add(chunk)
                return agg.finalize()

            response = await with_retry(_stream, state=self.recovery_state)
            self.ui.end_assistant_stream()

            # 7. max_tokens 截断处理
            if response.finish_reason == "max_tokens" and not self.recovery_state.has_escalated:
                max_tokens = self.escalated_max_tokens
                self.recovery_state.has_escalated = True
                self.memory.add_assistant(content=response.content, tool_calls=[])
                continue

            max_tokens = self.default_max_tokens
            self.recovery_state.has_escalated = False

            # 8. 如果没有工具调用, 说明 LLM 给出了最终回答
            if not response.tool_calls:
                await self.hooks.trigger(HookEvent.STOP)
                final_response = response.content
                break

            # 9. 记录 assistant 消息 (含 tool_calls)
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

            # 10. 处理所有工具调用
            #     拦截 compact → 走 summarization; 其余正常执行
            compacted = False
            for tc in response.tool_calls:
                if tc.name == "compact":
                    await self._handle_compact()
                    compacted = True
                    break
                await self._execute_tool_call(tc)

            # todo tracking
            if not compacted:
                has_todo = any(tc.name == "todo_write" for tc in response.tool_calls)
                rounds_since_todo = 0 if has_todo else (rounds_since_todo + 1)
            else:
                rounds_since_todo = 0

        else:
            # 超过最大迭代
            final_response = "达到最大工具调用次数，未找到最终答案。"
            self.ui.print_warning(final_response)

        return final_response

    # ── Compact handler ──

    async def _handle_compact(self) -> None:
        """Summarize conversation history and replace with compacted version."""
        try:
            compacted = await summary_compact(self.memory.messages, self.llm)
            self.memory.messages = compacted
            msg = "[Compacted. 对话历史已总结，继续工作。]"
            self.ui.print_info(msg)
            self.memory.add_user(msg)
        except Exception as e:
            self.ui.print_warning(f"Compact failed: {e}")

    # ── Tool execution ──

    async def _execute_tool_call(self, tc: Any) -> None:
        """执行单个工具调用。"""
        # Tool lookup via ToolPool or ToolRegistry
        tool = self.tools.get(tc.name) if hasattr(self.tools, "get") else None

        # Hook: PRE_TOOL_USE (在权限检查之前)
        blocked = await self.hooks.trigger(
            HookEvent.PRE_TOOL_USE,
            block_name=tc.name,
            block_input=tc.arguments,
        )
        if blocked:
            result_text = str(blocked)
            if result_text == "DESTRUCTIVE_PROMPT":
                description = (
                    getattr(tool, "description", "")
                    if tool
                    else tc.name
                )
                approved = await self.permissions.check(
                    tool_name=tc.name,
                    arguments=tc.arguments,
                    description=description,
                )
                if not approved:
                    result_text = f"工具调用 '{tc.name}' 被用户拒绝"
                else:
                    result = await self.tools.execute(tc.name, tc.arguments, approved=True)
                    result_text = result.content
                    await self.hooks.trigger(
                        HookEvent.POST_TOOL_USE,
                        block_name=tc.name,
                        result=result,
                    )
                    self.ui.print_tool_result(tc.name, result_text, is_error=result.is_error)
                    self.memory.add_tool(tc.id, tc.name, result_text)
                    return

            self.ui.print_tool_error(tc.name, tc.arguments, result_text)
            self.memory.add_tool(tc.id, tc.name, result_text)
            return

        # 权限检查
        approved = True
        if tool and getattr(tool, "requires_confirmation", False):
            approved = await self.permissions.check(
                tool_name=tc.name,
                arguments=tc.arguments,
                description=getattr(tool, "description", tc.name),
            )

        if not approved:
            result_text = f"工具调用 '{tc.name}' 被用户拒绝"
            self.ui.print_tool_rejected(tc.name, tc.arguments)
            self.memory.add_tool(tc.id, tc.name, result_text)
            return

        # 显示工具调用
        self.ui.print_tool_call(tc.name, tc.arguments)

        # 后台任务拦截：对慢速 bash 命令在后台执行
        if tc.name == "bash" and self.bg_manager:
            command = tc.arguments.get("command", "")
            if is_slow(command):
                placeholder = self.bg_manager.start(command, lambda: _exec_command(command))
                self.ui.print_tool_result(tc.name, placeholder, is_error=False)
                self.memory.add_tool(tc.id, tc.name, placeholder)
                return

        # 执行
        result = await self.tools.execute(tc.name, tc.arguments, approved=approved)

        # 显示结果
        self.ui.print_tool_result(tc.name, result.content, is_error=result.is_error)

        # 记录到 memory
        self.memory.add_tool(tc.id, tc.name, result.content)

        # Hook: POST_TOOL_USE
        await self.hooks.trigger(
            HookEvent.POST_TOOL_USE,
            block_name=tc.name,
            result=result,
        )
