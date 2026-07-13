"""ReAct 推理-行动循环。"""

from __future__ import annotations

import asyncio
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
        coordinator: Any = None,
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
        self.coordinator = coordinator

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

        _iteration = 0
        while _iteration < MAX_TOOL_ITERATIONS:
            _iteration += 1
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
                # 若有队友仍在运行或结果尚未收取, 阻塞轮询直至全部完成, 收集结果供总结
                # 参考 code.py: 以"邮箱是否有消息"为准, 不单独依赖 active 瞬时状态,
                # 队友先发结果再注销, 结果消息会晚于注销 —— 故用 pending 集(pending 仅在
                # 结果被主队友 consume 时才清除) 与 active 共同判定, 形成闭环。
                if self.coordinator and (
                    self.coordinator.has_pending_results()
                    or self.coordinator.get_active_teammates()
                ):
                    collected = await self._await_teammates()
                    if collected:
                        for m in collected:
                            fr = m.get("from", "?")
                            mtype = m.get("type", "result")
                            content = m.get("content", "")
                            log.info("Lead 收到队友 %s 的结果 (%d 字符)", fr, len(content))
                            self.ui.print_info(f"收到队友 {fr} 的结果")
                            self.ui.print_teammate_event(fr, f"已返回结果（{len(content)} 字）")
                            self.ui.print_tool_result(f"teammate:{fr}", content)
                            self.memory.add_user(
                                f"[队友 {fr} 的{mtype}]\n{content}"
                            )
                        self.memory.add_user(
                            "所有队友已完成。请汇总各队友的执行结果，"
                            "总结每个任务是成功还是失败，并给出最终结论。"
                        )
                        continue
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

            # 10b. 每轮工具调用后检查队友收件箱: 若所有队友皆已完成, 提前注入结果
            #     让 lead 可以及时汇总, 无需等到自己"无工具调用"才处理。
            if self.coordinator:
                drained = self.coordinator.consume_lead_inbox()
                results = [m for m in drained if m.get("type") == "result"]
                no_pending = not self.coordinator.has_pending_results()
                no_active = not self.coordinator.get_active_teammates()
                if results and no_pending and no_active:
                    for m in results:
                        fr = m.get("from", "?")
                        content = m.get("content", "")
                        self.ui.print_info(f"队友 {fr} 已完成（提前汇总）")
                        self.memory.add_user(f"[队友 {fr} 的结果]\n{content}")
                    self.memory.add_user(
                        "所有队友已完成。请汇总各队友的执行结果，"
                        "总结每个任务是成功还是失败，并给出最终结论。"
                    )
                    continue

            # todo tracking
            if not compacted:
                has_todo = any(tc.name == "todo_write" for tc in response.tool_calls)
                rounds_since_todo = 0 if has_todo else (rounds_since_todo + 1)
            else:
                rounds_since_todo = 0

        else:
            # 超过最大迭代: 若仍有队友在运行或结果未收取, 先等待收集再总结,
            # 避免主 lead 在队友完成前就草草收场 (闭环保证)。
            if self.coordinator and (
                self.coordinator.has_pending_results()
                or self.coordinator.get_active_teammates()
            ):
                collected = await self._await_teammates()
                if collected:
                    for m in collected:
                        fr = m.get("from", "?")
                        content = m.get("content", "")
                        self.ui.print_teammate_event(fr, f"已返回结果（{len(content)} 字）")
                        self.ui.print_tool_result(f"teammate:{fr}", content)
                        self.memory.add_user(
                            f"[队友 {fr} 的{m.get('type', 'result')}]\n{content}"
                        )
                    self.memory.add_user(
                        "已达迭代上限，但队友结果已就绪。请基于以下结果给出最终总结。"
                    )
                    # 再给一轮 LLM 调用做总结
                    self.memory.refresh_system_prompt()
                    self.ui.start_assistant_stream()

                    _tools = tool_schemas
                    _mtokens = max_tokens

                    async def _final_stream(_t: Any = _tools, _m: int = _mtokens):
                        agg = StreamAggregator()
                        async for chunk in self.llm.stream(
                            messages=self.memory.messages,
                            tools=_t,
                            max_tokens=_m,
                        ):
                            if chunk.content:
                                self.ui.update_assistant_stream(chunk.content)
                            agg.add(chunk)
                        return agg.finalize()

                    fr_resp = await with_retry(_final_stream, state=self.recovery_state)
                    self.ui.end_assistant_stream()
                    final_response = fr_resp.content
                else:
                    final_response = "达到最大工具调用次数，且未收到队友结果。"
                    self.ui.print_warning(final_response)
            else:
                final_response = "达到最大工具调用次数，未找到最终答案。"
                self.ui.print_warning(final_response)

        return final_response

    # ── Teammate wait handler ──

    async def _await_teammates(self, timeout: float = 600.0) -> list[dict[str, Any]]:
        """阻塞轮询, 等待所有已派生队友的结果到达并收集 (闭环)。

        终止条件: 既无待收结果(pending 集), 也无活跃队友(active)。前者仅在结果
        被 consume 时清除, 后者在队友注销时清除 —— 二者都满足才说明闭环结束。
        轮询期间非破坏性检查, 仅在结果到达时 consume, 避免 code.py 提到的
        "结果晚于注销"竞态。
        """
        self.ui.print_info("等待队友完成任务...")
        collected: list[dict[str, Any]] = []
        elapsed = 0.0
        while (
            (self.coordinator.has_pending_results()
             or self.coordinator.get_active_teammates())
            and elapsed < timeout
        ):
            collected.extend(self.coordinator.consume_lead_inbox())
            await asyncio.sleep(1.0)
            elapsed += 1.0
        # 最终 drain: 捕获边界情况下刚到达的结果
        collected.extend(self.coordinator.consume_lead_inbox())
        return collected

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
