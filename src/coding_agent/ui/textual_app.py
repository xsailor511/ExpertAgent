"""Modern TUI for Coding Agent - Built with Textual, similar to Claude Code."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from contextlib import suppress
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.events import Key
from textual.widgets import Button, Header, Input, Label, ListItem, ListView, Static
from textual.worker import Worker

from coding_agent.core.agent import Agent
from coding_agent.ui.terminal import TerminalUI

# 流式渲染保护：长文本下如果每 chunk 都重渲染整段会让 TUI 卡死
STREAM_REFRESH_INTERVAL = 0.06  # 节流：最多 ~16 次/秒刷新
STREAM_MAX_CHARS = 4000  # 流式显示上限，超出截断（开头+结尾），结束后再显示完整
STREAM_HEAD_CHARS = 3000
STREAM_TAIL_CHARS = 800


class CompletableInput(Input):
    """Input that intercepts navigation keys when suggestions are active."""

    def on_key(self, event: Key) -> None:
        app: CodingAgentApp = self.app  # type: ignore[assignment]
        if app._suggestions_active and event.key in ("up", "down", "tab", "escape", "enter"):
            event.stop()
            event.prevent_default()
            if event.key == "up":
                app._suggestion_prev()
            elif event.key == "down":
                app._suggestion_next()
            elif event.key in ("tab", "enter"):
                app._suggestion_select()
            elif event.key == "escape":
                app._hide_suggestions()


def _summarize_args(name: str, arguments: dict[str, Any]) -> str:
    if name == "bash":
        cmd = arguments.get("command", "")
        return cmd[:80] + "..." if len(cmd) > 80 else cmd
    if name in ("read_file", "write_file", "edit_file"):
        path = arguments.get("path", "")
        return path[:60] + "..." if len(path) > 60 else path
    if name == "search":
        query = arguments.get("query", "")
        return f'"{query}"'
    return json.dumps(arguments, ensure_ascii=False)[:80]


def _summarize_result(name: str, result: str) -> str:
    return result


class TextualUIAdapter(TerminalUI):
    """Textual UI adapter — drives the TUI from the agent loop."""

    def __init__(self, app_instance: CodingAgentApp):
        super().__init__()
        self.app = app_instance
        self._user_msg_shown = False
        self._is_streaming = False
        self._buffer = ""
        self._has_content = False
        self.assistant_bubble: Static | None = None
        self.msg_wrapper: Container | None = None
        self._last_stream_update = 0.0

    def _safe_app_call(self, method, *args: Any) -> None:
        """Call method on the app thread, or directly if already there."""
        try:
            self.app.call_from_thread(method, *args)
        except RuntimeError:
            method(*args)

    def _create_bubble_sync(self) -> None:
        if self.assistant_bubble is not None:
            return
        try:
            self.assistant_bubble = Static("", classes="assistant-bubble")
            self.msg_wrapper = Container(
                self.assistant_bubble, classes="message-wrapper message-assistant"
            )
            self.app.chat_container.mount(self.msg_wrapper)
        except Exception:
            pass

    def print_user(self, text: str) -> None:
        if self._user_msg_shown:
            self._user_msg_shown = False
            return
        self.app._add_item("user", text)

    def start_assistant_stream(self) -> None:
        self._buffer = ""
        self._is_streaming = True
        self._has_content = False
        self.assistant_bubble = None
        self.msg_wrapper = None
        self.app.thinking_label.update("🤔 Thinking...")
        self.app.info_status.update("Status: streaming")

    def update_assistant_stream(self, chunk: str) -> None:
        if not self._is_streaming:
            return
        if not self._has_content:
            if not chunk.strip():
                return
            self._has_content = True
            self._buffer = chunk
            self._create_bubble_sync()
        else:
            self._buffer = (self._buffer or "") + chunk
        if self.assistant_bubble is None:
            return
        # 节流：限制刷新频率，避免长文本下反复重渲染整段导致 TUI 卡死
        now = time.monotonic()
        if now - self._last_stream_update < STREAM_REFRESH_INTERVAL and (
            len(self._buffer) < STREAM_MAX_CHARS
        ):
            return
        self._last_stream_update = now
        self.assistant_bubble.update(self._render_stream_buffer())
        self.assistant_bubble.refresh(layout=True)
        try:
            sv = self.app.query_one("#chat-area", ScrollableContainer)
            sv.scroll_end(animate=False)
        except Exception:
            pass

    def _render_stream_buffer(self) -> str:
        """流式显示用：超长文本截断，仅保留开头与结尾，避免 TUI 卡死。"""
        buf = self._buffer or ""
        if len(buf) <= STREAM_MAX_CHARS:
            return buf
        omitted = len(buf) - STREAM_HEAD_CHARS - STREAM_TAIL_CHARS
        return (
            buf[:STREAM_HEAD_CHARS]
            + f"\n\n…（已省略中间约 {omitted} 字，流式输出完成后将显示完整内容）\n\n"
            + buf[-STREAM_TAIL_CHARS:]
        )

    def end_assistant_stream(self) -> None:
        self._is_streaming = False
        if self._has_content and self.assistant_bubble is not None:
            display = self._buffer.strip() if (self._buffer or "").strip() else "(no content)"
            self.assistant_bubble.update(display)
            self.assistant_bubble.refresh(layout=True)
        elif self._buffer and not self._buffer.strip() and self.msg_wrapper is not None:
            with suppress(Exception):
                self.msg_wrapper.remove()
        self.assistant_bubble = None
        self.msg_wrapper = None
        self.app.thinking_label.update("Ready")
        self.app.info_status.update("Status: processing")
        self.app.input.focus()

    def print_tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        summary = _summarize_args(name, arguments)
        self.app._add_item("tool", f"🔧 {name}  {summary}")
        self.app.info_status.update(f"Status: ⚡ {name}")

    def print_tool_result(self, name: str, result: str, *, is_error: bool = False) -> None:
        if result:
            display = _summarize_result(name, result)
            kind = "tool-error" if is_error else "tool-result"
            self.app._add_item(kind, display)
        self.app.info_status.update(f"Status: {'❌' if is_error else '✅'} {name}")

    def print_tool_error(self, name: str, arguments: dict[str, Any], error: str) -> None:
        summary = _summarize_args(name, arguments)
        self.app._add_item("tool", f"🔧 {name}  {summary}  ❌ {error[:120]}")

    def print_tool_rejected(self, name: str, arguments: dict[str, Any]) -> None:
        summary = _summarize_args(name, arguments)
        self.app._add_item("tool", f"🚫 {name}  {summary}  rejected")

    def print_info(self, msg: str) -> None:
        self.app.thinking_label.update(msg)

    def print_warning(self, msg: str) -> None:
        self._safe_app_call(self.app._add_item, "assistant", f"⚠ {msg}")
        with suppress(Exception):
            self.app.thinking_label.update("⚠ ...")

    def print_error(self, msg: str) -> None:
        self.app._add_item("error", f"✖ {msg}")
        self.app.info_status.update("Status: error")

    def print_success(self, msg: str) -> None:
        self.app.thinking_label.update(f"✔ {msg}")

    # ── TUI-native confirmation (replaces TerminalUI.input()) ──

    def confirm(self, prompt: str, default: bool = False) -> bool:
        event = threading.Event()
        result: list[bool] = [default]

        def _show_prompt() -> None:
            self.app._pending_confirm_event = event
            self.app._pending_confirm_result = result
            self.app._add_item("assistant", prompt)
            self.app.input.placeholder = "输入 y (允许) 或 n (拒绝): "
            self.app.input.focus()

        self._safe_app_call(_show_prompt)

        event.wait(timeout=120)

        def _cleanup() -> None:
            self.app._pending_confirm_event = None
            self.app.input.placeholder = "Ask me anything about coding..."

        self._safe_app_call(_cleanup)
        return result[0]

    # ── SubAgent lightweight log mode ──

    def print_subagent_start(self, description: str) -> None:
        self._safe_app_call(self.app._add_item, "subagent-start", f"🔄 SubAgent: {description}")
        self._safe_app_call(self.app._add_activity, "SubAgent", description, "running")

    def print_subagent_milestone(self, msg: str) -> None:
        self._safe_app_call(self.app._add_item, "subagent-milestone", f"  · {msg}")

    def print_subagent_end(self, summary: str) -> None:
        display = summary or "(no output)"
        self._safe_app_call(self.app._add_item, "subagent-end", display)
        self._safe_app_call(self.app._update_activity, "SubAgent", "completed")

    # ── Teammate event-driven display ──

    def print_teammate_progress(self, name: str, msg: str) -> None:
        self._safe_app_call(self.app._update_teammate_progress, name, msg)

    def print_teammate_complete(self, name: str, msg: str) -> None:
        self._safe_app_call(self.app._add_teammate_event, name, msg)
        with suppress(Exception):
            self.app.info_status.update(f"Status: 🤖 {name}")

    # 保留旧别名保证向后兼容
    def print_teammate_event(self, name: str, msg: str) -> None:
        self.print_teammate_complete(name, msg)


class CodingAgentApp(App):
    """Main TUI application class – multi-type item list."""

    CSS = """
    Screen {
        background: #1e1e2e;
    }

    /* ── Chat area ── */
    #chat-area {
        height: 1fr;
        margin: 1 2 0 2;
        border: none;
        background: transparent;
    }

    #chat-container {
        padding: 1 1;
        height: auto;
    }

    .message-wrapper {
        width: 100%;
        margin: 1 0;
        height: auto;
    }

    /* ── User messages ── */
    .user-bubble {
        background: transparent;
        color: #89b4fa;
        padding: 1 1;
        border-left: solid #89b4fa;
        width: 100%;
        height: auto;
    }

    /* ── Assistant messages ── */
    .assistant-bubble {
        background: transparent;
        color: #cdd6f4;
        padding: 1 1;
        border-left: solid #a6e3a1;
        width: 100%;
        height: auto;
        min-height: 1;
    }

    /* ── Tool invocations ── */
    .tool-bubble {
        background: transparent;
        color: #fab387;
        padding: 0 1;
        border-left: solid #fab387;
        width: 100%;
        height: auto;
    }

    /* ── Tool results (success) ── */
    .tool-result-bubble {
        background: transparent;
        color: #585b70;
        padding: 0 1 0 2;
        border-left: solid #585b70;
        width: 100%;
        height: auto;
        min-height: 1;
    }

    /* ── Tool results (error) ── */
    .tool-error-bubble {
        background: transparent;
        color: #f38ba8;
        padding: 0 1 0 2;
        border-left: solid #f38ba8;
        width: 100%;
        height: auto;
        min-height: 1;
    }

    /* ── Error messages ── */
    .error-bubble {
        background: transparent;
        color: #f38ba8;
        padding: 1 1;
        border-left: solid #f38ba8;
        width: 100%;
        height: auto;
        min-height: 1;
    }

    /* ── SubAgent bubbles (magenta) ── */
    .subagent-start-bubble {
        background: transparent;
        color: #cba6f7;
        padding: 1 1;
        border-left: solid #cba6f7;
        width: 100%;
        height: auto;
    }

    .subagent-milestone-bubble {
        background: transparent;
        color: #585b70;
        padding: 0 1 0 2;
        border-left: solid #cba6f7;
        width: 100%;
        height: auto;
    }

    .subagent-end-bubble {
        background: transparent;
        color: #a6e3a1;
        padding: 1 1;
        border-left: solid #a6e3a1;
        width: 100%;
        height: auto;
    }

    /* ── Teammate bubbles (gold) ── */
    .teammate-event-bubble {
        background: transparent;
        color: #f9e2af;
        padding: 1 1;
        border-left: solid #f9e2af;
        width: 100%;
        height: auto;
    }

    /* ── Main area (chat + teammate panel) ── */
    #main-area {
        height: 1fr;
    }

    /* ── Teammate side panel ── */
    #teammate-panel {
        width: 30;
        background: #181825;
        border-left: solid #313244;
        padding: 0 1;
        display: none;
        overflow-y: auto;
    }

    #teammate-panel.visible {
        display: block;
    }

    .teammate-panel-title {
        height: 1;
        color: #a6adc8;
        padding: 1 0;
        text-style: bold;
    }

    .teammate-card {
        border: solid #45475a;
        margin: 1 0;
        padding: 1;
        max-height: 10;
        overflow-y: auto;
    }

    .teammate-card-name {
        height: 1;
        color: #f9e2af;
        text-style: bold;
    }

    .teammate-card-status {
        height: 1;
        color: #585b70;
    }

    .teammate-card-task {
        height: auto;
        color: #585b70;
    }

    .teammate-card-events {
        height: auto;
        color: #6c7086;
    }

    /* ── Thinking label ── */
    #thinking-label {
        height: 1;
        margin: 0 2;
        color: #a6adc8;
        padding: 0;
    }

    /* ── Activity panel ── */
    #activity-panel {
        height: auto;
        max-height: 6;
        margin: 0 2 1 2;
        background: #181825;
        border: none;
        padding: 0;
    }

    #activity-container {
        height: auto;
        padding: 0 1;
    }

    .activity-entry {
        height: 1;
        padding: 0;
        color: #585b70;
    }

    .activity-entry.running  { color: #f9e2af; }
    .activity-entry.completed { color: #585b70; }
    .activity-entry.failed    { color: #f38ba8; }
    .activity-entry.cancelled { color: #6c7086; }

    /* ── Suggestions ── */
    #suggestion-list {
        display: none;
        height: auto;
        margin: 0;
        background: #181825;
        border: tall #45475a;
        padding: 0;
    }

    #suggestion-list ListItem {
        height: 1;
        min-height: 1;
        padding: 0 1;
    }

    /* ── New-conversation divider ── */
    .conversation-divider {
        width: 100%;
        height: auto;
        layout: horizontal;
    }
    .divider-line {
        width: 1fr;
        color: #585b70;
        text-style: dim;
        height: 1;
    }
    .divider-text {
        width: auto;
        color: #585b70;
        padding: 0 1;
        text-style: dim;
    }

    /* ── Input area ── */
    #input-area {
        height: 3;
        margin: 0 2;
        background: transparent;
        padding: 0;
    }

    #input-area Input {
        width: 1fr;
        background: #181825;
        color: #cdd6f4;
        border: tall #45475a;
        padding: 0 1;
    }

    #input-area Input:focus {
        border: tall #89b4fa;
    }

    /* ── Info row ── */
    #info-row {
        height: 1;
        margin: 1 2 1 2;
    }

    .info-cell {
        width: auto;
        color: #585b70;
        padding: 0;
        margin-right: 2;
    }

    .info-cell:last-child {
        margin-right: 0;
    }

    /* ── Header ── */
    Header {
        background: #1e1e2e;
        color: #cdd6f4;
        padding: 0 2;
    }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("enter", "send_message_action", "Send message"),
        ("esc", "clear_input_action", "Clear input"),
    ]

    def __init__(self, agent: Agent | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.textual_ui_adapter = TextualUIAdapter(self)
        if agent is not None:
            self.agent = agent
            self.agent.set_ui(self.textual_ui_adapter)
        else:
            self.agent = Agent.from_settings()
            self.agent.set_ui(self.textual_ui_adapter)
        self.is_processing = False
        self.should_exit = False
        self._suggestions_active = False
        self._suggestions_readonly = False
        self._suggestion_commands: list[str] = []
        self.SUGGESTION_COMMANDS = [
            "/exit",
            "/quit",
            "/q",
            "/new",
            "/clear",
            "/compact",
            "/help",
            "/skills",
            "/mcp",
        ]
        self._activity_count = 0
        self._max_activities = 20
        self._agent_worker: Worker | None = None
        self._teammate_cards: dict[str, Container] = {}
        self._teammate_events: dict[str, list[str]] = {}
        self._pending_confirm_event: threading.Event | None = None
        self._pending_confirm_result: list[bool] = [False]

    # ── Info row ──

    def _update_context_info(self) -> None:
        try:
            memory = self.agent.memory
            used = memory.token_count()
            limit = getattr(memory, "max_tokens", 0) or 0
            self.info_context.update(f"Context: {used}/{limit}")
        except Exception:
            pass

    def _sync_ime_cursor(self) -> None:
        if os.name != "nt":
            return
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            imm32 = ctypes.windll.imm32
            col = self.input.region.x + 1
            row = self.input.region.y + 1
            con_out = kernel32.GetStdHandle(-11)
            packed = ctypes.c_uint32(col | (row << 16))
            kernel32.SetConsoleCursorPosition(con_out, packed)
            hwnd = kernel32.GetConsoleWindow()
            if hwnd:
                himc = imm32.ImmGetContext(hwnd)
                if himc:
                    style = ctypes.c_uint32(1)
                    pt_x = ctypes.c_int32(col * 8)
                    pt_y = ctypes.c_int32(row * 16)
                    buf = (ctypes.c_uint32 * 3)(style.value, pt_x.value, pt_y.value)
                    imm32.ImmSetCompositionWindow(himc, buf)
                    imm32.ImmReleaseContext(hwnd, himc)
        except Exception:
            pass

    def on_key(self, event: Key) -> None:
        if self.should_exit:
            self.exit()

    # ── Layout ──

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main-area"):
            with ScrollableContainer(id="chat-area"), Vertical(id="chat-container"):
                pass
            with ScrollableContainer(id="teammate-panel"):
                yield Static("🤖 队友", classes="teammate-panel-title")
                yield Vertical(id="teammate-container")
        yield Label("Ready", id="thinking-label")
        with ScrollableContainer(id="activity-panel"), Vertical(id="activity-container"):
            pass
        yield ListView(id="suggestion-list")
        with Horizontal(id="input-area"):
            yield CompletableInput(placeholder="Ask me anything about coding...", id="input")
        with Horizontal(id="info-row"):
            yield Label("───", id="info-status", classes="info-cell")
            yield Label("───", id="info-model", classes="info-cell")
            yield Label("───", id="info-context", classes="info-cell")

    def on_mount(self) -> None:
        self.chat_container = self.query_one("#chat-container", Vertical)
        self.activity_container = self.query_one("#activity-container", Vertical)
        self.input = self.query_one("#input", Input)
        self.thinking_label = self.query_one("#thinking-label", Label)
        self.info_status = self.query_one("#info-status", Label)
        self.info_model = self.query_one("#info-model", Label)
        self.info_context = self.query_one("#info-context", Label)
        self.teammate_container = self.query_one("#teammate-container", Vertical)
        self.teammate_panel = self.query_one("#teammate-panel", ScrollableContainer)
        self._teammate_cards: dict[str, Container] = {}
        try:
            model = getattr(self.agent.llm, "model", None) or "───"
            self.info_model.update(f"Model: {model}")
        except Exception:
            pass
        self._update_context_info()
        self._add_item(
            "assistant",
            "👋 Hello! I'm your AI coding assistant."
            "\nAsk me any programming question, and I'll do my best to help!",
        )
        self.thinking_label.update("Ready")
        self.info_status.update("Status: idle")
        self.input.focus()
        self._sync_ime_cursor()
        self.set_interval(1, self._poll_cron)

    async def _poll_cron(self) -> None:
        """Periodic cron poll — process fired tasks when agent is idle."""
        if self.is_processing:
            return
        cron = getattr(self.agent, "cron", None)
        if not cron:
            return
        fired = cron.pop_fired()
        if not fired:
            return
        self.is_processing = True
        prompts_text = " | ".join(f"[Cron] {p}" for p in fired)
        self.thinking_label.update("🤔 Thinking...")
        self.info_status.update("Status: streaming")
        await self.process_agent_response(prompts_text)

    # ── Multi-type list items ──

    def _get_skill_suggestions(self) -> list[str]:
        skills = []
        try:
            reg = self.agent.memory.skill_registry
            if reg:
                for info in reg.list_skill_dicts():
                    desc = info["description"].replace("\n", " ")
                    if len(desc) > 50:
                        desc = desc[:50] + "…"
                    markup = (
                        f"[bold][#89b4fa]{info['name']}[/#89b4fa][/bold] "
                        f"[dim][#585b70]{desc}[/#585b70][/dim]"
                    )
                    skills.append(markup)
        except Exception:
            pass
        return skills

    def _get_mcp_status(self) -> list[str]:
        items = []
        try:
            pool = self.agent.tools
            configured = getattr(pool, "_mcp_config_servers", [])
            if not configured:
                return []
            failures = getattr(pool, "_mcp_failures", {})
            for name in configured:
                if name in pool._mcp_clients:
                    items.append(f"[bold][green]{name} (已连接)[/green][/bold]")
                elif name in failures:
                    items.append(f"[bold][red]{name} (连接失败)[/red][/bold]")
        except Exception:
            pass
        return items

    @staticmethod
    def _truncate_lines(text: str, max_lines: int = 5) -> str:
        """Truncate text to max_lines of content, adding a hint for overflow."""
        lines = text.split("\n")
        if len(lines) <= max_lines:
            return text
        extra = len(lines) - max_lines
        return "\n".join(lines[:max_lines]) + f"\n... (更多{extra}行)"

    def _add_item(self, kind: str, text: str) -> None:
        """Add an item of a given kind to the chat list.

        kind ∈ {user, assistant, tool, tool-result, tool-error, error,
                subagent-start, subagent-milestone, subagent-end, teammate-event}
        """
        no_truncate = {"user", "assistant", "subagent-end", "teammate-event"}
        if kind not in no_truncate:
            text = self._truncate_lines(text)
        entry = ITEM_MAP.get(kind)
        if entry is None:
            bubble = Static(text, classes="assistant-bubble")
            wrapper = Container(bubble, classes="message-wrapper message-assistant")
        else:
            bubble_cls, wrapper_cls = entry
            bubble = Static(text, classes=bubble_cls)
            wrapper = Container(bubble, classes=f"message-wrapper {wrapper_cls}")
        self.chat_container.mount(wrapper)
        try:
            sv = self.query_one("#chat-area", ScrollableContainer)
            sv.scroll_end(animate=False)
        except Exception:
            pass

    # ── Activity panel ──

    @staticmethod
    def _activity_icon(status: str) -> str:
        icons = {"running": "⏳", "completed": "✅", "failed": "❌", "cancelled": "🚫"}
        return icons.get(status, "🔧")

    def _add_activity(self, name: str, summary: str, status: str) -> None:
        icon = self._activity_icon(status)
        self._activity_count += 1
        label = Label(f" {icon} {name}  {summary}", classes=f"activity-entry {status}")
        self.activity_container.mount(label)
        if self._activity_count > self._max_activities:
            first = self.activity_container.children[0]
            if first is not None:
                first.remove()
        try:
            ap = self.query_one("#activity-panel", ScrollableContainer)
            ap.scroll_end(animate=False)
        except Exception:
            pass

    def _update_activity(self, name: str, status: str) -> None:
        icon = self._activity_icon(status)
        for child in reversed(list(self.activity_container.children)):
            if isinstance(child, Label) and name in child.classes:
                child.classes = f"activity-entry {status}"
                text = child.renderable or ""
                prefix = text[:2]
                if prefix in (" ⏳", " ✅", " ❌", " 🚫"):
                    text = f" {icon}" + text[2:]
                    child.update(text)
                break

    def _clear_activities(self) -> None:
        self.activity_container.remove_children()

    # ── Teammate panel ──

    def _init_teammate_card(self, name: str, task: str = "") -> None:
        card = Container(
            Label(f"🤖 {name}", classes="teammate-card-name"),
            Label("状态: 工作中...", classes="teammate-card-status", id=f"tstatus-{name}"),
            Label(task[:60], classes="teammate-card-task", id=f"ttask-{name}"),
            Static("", classes="teammate-card-events", id=f"tevents-{name}"),
            classes="teammate-card",
            id=f"teammate-card-{name}",
        )
        card.styles.display = "block"
        self._teammate_cards[name] = card
        self.teammate_container.mount(card)
        self.teammate_panel.styles.display = "block"

    def _update_teammate_card(self, name: str, task: str = "", status: str = "") -> None:
        card = self._teammate_cards.get(name)
        if card is None:
            return
        if status:
            status_label = card.query_one(f"#tstatus-{name}", Label)
            status_label.update(f"状态: {status}")
        if task:
            task_label = card.query_one(f"#ttask-{name}", Label)
            task_label.update(task[:60])

    def _append_teammate_event(self, name: str, msg: str) -> None:
        card = self._teammate_cards.get(name)
        if card is None:
            return
        events = card.query_one(f"#tevents-{name}", Static)
        if name not in self._teammate_events:
            self._teammate_events[name] = []
        self._teammate_events[name].append(f"  {msg}")
        events.update("\n".join(self._teammate_events[name][-6:]))

    def _remove_teammate_card(self, name: str) -> None:
        card = self._teammate_cards.pop(name, None)
        if card is not None:
            card.remove()
        self._teammate_events.pop(name, None)
        if not self._teammate_cards:
            self.teammate_panel.styles.display = "none"

    def _update_teammate_progress(self, name: str, msg: str) -> None:
        """Update side panel only — no chat bubble. Used during execution."""
        if name not in self._teammate_cards:
            self._init_teammate_card(name, task=msg)
        self._update_teammate_card(name, task=msg, status="工作中...")
        self._append_teammate_event(name, msg)

    def _add_teammate_event(self, name: str, msg: str) -> None:
        """Add a teammate completion bubble to chat and update side panel."""
        if name not in self._teammate_cards:
            self._init_teammate_card(name, task=msg)
        self._add_item("teammate-event", f"[{name}] {msg}")
        self._append_teammate_event(name, msg)
        self._update_teammate_card(name, status="已完成")

    # ── Input events ──

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._suggestions_active:
            self._suggestion_select()
            return
        text = event.value.strip()

        # Handle pending confirmation (even during processing)
        if self._pending_confirm_event is not None:
            self.input.value = ""
            if text.lower() in ("y", "yes"):
                self._pending_confirm_result[0] = True
            elif text.lower() in ("n", "no", ""):
                self._pending_confirm_result[0] = False
            else:
                self.input.placeholder = "输入 y (允许) 或 n (拒绝): "
                return
            self._pending_confirm_event.set()
            return

        if not text or self.is_processing:
            return
        if text.startswith("/"):
            self._handle_slash_command(text)
        else:
            self.send_message()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if getattr(event.button, "id", None) == "send-btn":
            text = self.input.value.strip()
            if not text or self.is_processing:
                return
            if text.startswith("/"):
                self._handle_slash_command(text)
            else:
                self.send_message()

    def action_quit(self) -> None:
        """Cancel running agent, close MCP subprocesses, then exit the app."""
        # Cancel any in-flight agent worker first
        if self._agent_worker and self._agent_worker.is_running:
            self._agent_worker.cancel()
        with suppress(Exception):
            self.agent.tools.close()
        self.should_exit = True
        self.exit()

    def action_send_message_action(self) -> None:
        if self._suggestions_active:
            self._suggestion_select()
        text = self.input.value.strip()
        if not text or self.is_processing:
            return
        if text.startswith("/"):
            self._handle_slash_command(text)
        else:
            self.send_message()

    def action_clear_input_action(self) -> None:
        self.input.value = ""

    def _handle_slash_command(self, command: str) -> None:
        cmd = command.strip().lower()
        if cmd in ("/exit", "/quit", "/q"):
            self.input.value = ""
            self.action_quit()
            return
        if cmd == "/new":
            self.input.value = ""
            self.agent.memory.clear()
            divider = Horizontal(
                Static("─" * 500, classes="divider-line"),
                Static(" 新对话 ", classes="divider-text"),
                Static("─" * 500, classes="divider-line"),
                classes="conversation-divider",
            )
            self.chat_container.mount(divider)
            self.thinking_label.update("Ready")
            self.info_status.update("Status: idle")
            self._update_context_info()
            try:
                sv = self.query_one("#chat-area", ScrollableContainer)
                sv.scroll_end(animate=False)
            except Exception:
                pass
            return
        if cmd == "/clear":
            self._add_item("user", command)
            self.input.value = ""
            self.chat_container.remove_children()
            self._clear_activities()
            self._add_item(
                "assistant",
                "Chat history cleared."
                " Ask me any programming question, and I'll do my best to help!",
            )
            self.thinking_label.update("Ready")
            self.info_status.update("Status: idle")
            self._update_context_info()
            return
        if cmd == "/compact":
            self._add_item("user", command)
            self.input.value = ""
            self.thinking_label.update("Compacting...")
            self.info_status.update("Status: compacting")
            self.is_processing = True
            self._agent_worker = self.run_worker(self._run_compact())
            return
        if cmd == "/skills":
            self._add_item("user", command)
            skills = self._get_skill_suggestions()
            if skills:
                self._show_suggestions(skills)
            else:
                msg = "No skills found. Add skill files to ~/.coding-agent/skills/"
                self._add_item("assistant", msg)
            self.input.focus()
            return
        if cmd == "/mcp":
            self._add_item("user", command)
            items = self._get_mcp_status()
            if items:
                self._show_suggestions(items, readonly=True)
            else:
                self._add_item("assistant", "No MCP servers configured.")
            self.input.focus()
            return
        if cmd == "/help":
            self._add_item("user", command)
            help_text = (
                "Available commands:\n"
                "  /new    - Start new conversation (clear memory, keep chat visible)\n"
                "  /mcp    - List MCP server connection status\n"
                "  /skills - List available skills\n"
                "  /exit   - Exit the application\n"
                "  /quit   - Exit the application\n"
                "  /q      - Exit the application\n"
                "  /clear  - Clear chat history\n"
                "  /compact - LLM-summarize conversation to compact context\n"
                "  /help   - Show this help message"
            )
            self._add_item("assistant", help_text)
            return
        self._add_item("user", command)
        self._add_item("error", f"Unknown command: '{command}'. Type /help for available commands.")

    def on_input_changed(self, event: Input.Changed) -> None:
        value = event.value.strip()
        if value.startswith("/"):
            if value in self.SUGGESTION_COMMANDS:
                self._hide_suggestions()
                return
            matched = [cmd for cmd in self.SUGGESTION_COMMANDS if cmd.startswith(value)]
            if matched:
                self._show_suggestions(matched)
            else:
                self._hide_suggestions()
        else:
            self._hide_suggestions()

    def _show_suggestions(self, commands: list[str], readonly: bool = False) -> None:
        self._suggestion_commands = commands
        self._suggestions_readonly = readonly
        sv = self.query_one("#suggestion-list", ListView)
        sv.clear()
        max_visible = 6 if readonly else 12
        sv.styles.max_height = min(len(commands), max_visible) + 2
        for cmd in commands:
            label = Label(cmd)
            label.styles.padding = 0
            sv.append(ListItem(label))
        if sv.children:
            sv.index = 0
        sv.styles.display = "block"
        self._suggestions_active = True

    def _hide_suggestions(self) -> None:
        sv = self.query_one("#suggestion-list", ListView)
        sv.clear()
        sv.styles.display = "none"
        self._suggestions_active = False

    def _suggestion_prev(self) -> None:
        sv = self.query_one("#suggestion-list", ListView)
        if not sv.children:
            return
        if sv.index is None or sv.index <= 0:
            sv.index = len(sv.children) - 1
        else:
            sv.index -= 1

    def _suggestion_next(self) -> None:
        sv = self.query_one("#suggestion-list", ListView)
        if not sv.children:
            return
        if sv.index is None:
            sv.index = 0
        else:
            sv.index = (sv.index + 1) % len(sv.children)

    def _suggestion_select(self) -> None:
        if self._suggestions_readonly:
            self._hide_suggestions()
            return
        sv = self.query_one("#suggestion-list", ListView)
        if sv.index is not None and sv.index < len(self._suggestion_commands):
            cmd = self._suggestion_commands[sv.index]
            if not cmd.startswith("/"):
                m = re.search(r"\[#89b4fa\]([\w-]+)\[/#89b4fa\]", cmd)
                if m:
                    self.input.value = m.group(1) + " "
                    self.input.cursor_position = len(m.group(1)) + 1
                else:
                    self.input.value = cmd
                    self.input.cursor_position = len(cmd)
            else:
                self.input.value = cmd
                self.input.cursor_position = len(cmd)
        self._hide_suggestions()

    # ── Message send / process ──

    def send_message(self) -> None:
        text = self.input.value.strip()
        if not text or self.is_processing:
            return

        first_word = text.split()[0] if text.split() else ""
        skill_content = None
        try:
            reg = self.agent.memory.skill_registry
            if reg and first_word:
                skill_content = reg.get_enriched_content(first_word)
        except Exception:
            pass

        final_text = text
        if skill_content:
            rest = text[len(first_word) :].strip() if len(first_word) < len(text) else ""
            final_text = f"[Attached Skill: {first_word}]\n```skill\n{skill_content}\n```\n\n{rest}"

        self._add_item("user", text)
        self.textual_ui_adapter._user_msg_shown = True
        self.input.value = ""
        self.thinking_label.update("🤔 Thinking...")
        self.info_status.update("Status: streaming")
        self.is_processing = True
        self._agent_worker = self.run_worker(self.process_agent_response(final_text))

    async def _run_compact(self) -> None:
        """LLM 极限压缩上下文：总结历史后替换为精炼摘要，并刷新页面。"""
        try:
            from coding_agent.core.compaction import summary_compact

            compacted = await summary_compact(
                self.agent.memory.messages,
                self.agent.llm,
            )
            self.agent.memory.messages = compacted
            self.chat_container.remove_children()
            self._clear_activities()
            self._add_item(
                "assistant",
                "Context compacted. Conversation history summarized via LLM.",
            )
        except Exception as e:
            from coding_agent.core.compaction import reactive_compact

            self.agent.memory.messages = reactive_compact(self.agent.memory.messages)
            self.chat_container.remove_children()
            self._clear_activities()
            self._add_item(
                "assistant",
                f"LLM compact failed ({e}), fallback: reactive truncation applied.",
            )
        finally:
            self.thinking_label.update("Ready")
            self.info_status.update("Status: idle")
            self.is_processing = False
            self._update_context_info()

    async def process_agent_response(self, user_text: str) -> None:
        try:
            await self.agent.run(user_text)
            self.thinking_label.update("Ready")
            self.info_status.update("Status: idle")
        except Exception as e:
            self._add_item("error", str(e))
            self.thinking_label.update("❌ Error occurred")
            self.info_status.update("Status: error")
        finally:
            self.is_processing = False
            self._update_context_info()
            try:
                sv = self.query_one("#chat-area", ScrollableContainer)
                sv.scroll_end(animate=True)
            except Exception:
                pass


ITEM_MAP: dict[str, tuple[str, str]] = {
    "user": ("user-bubble", "message-user"),
    "assistant": ("assistant-bubble", "message-assistant"),
    "tool": ("tool-bubble", "message-tool"),
    "tool-result": ("tool-result-bubble", "message-tool-result"),
    "tool-error": ("tool-error-bubble", "message-tool-error"),
    "error": ("error-bubble", "message-error"),
    "subagent-start": ("subagent-start-bubble", "message-subagent-start"),
    "subagent-milestone": ("subagent-milestone-bubble", "message-subagent-milestone"),
    "subagent-end": ("subagent-end-bubble", "message-subagent-end"),
    "teammate-event": ("teammate-event-bubble", "message-teammate-event"),
}
