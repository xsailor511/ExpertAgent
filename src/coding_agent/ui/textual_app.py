"""Modern TUI for Coding Agent - Built with Textual, similar to Claude Code."""

from __future__ import annotations

import json
import os
import re
from contextlib import suppress
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.events import Key
from textual.widgets import Button, Header, Input, Label, ListItem, ListView, Static
from textual.worker import Worker

from coding_agent.core.agent import Agent
from coding_agent.ui.terminal import TerminalUI


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
        self.assistant_bubble.update(self._buffer)
        self.assistant_bubble.refresh(layout=True)
        try:
            sv = self.app.query_one("#chat-area", ScrollableContainer)
            sv.scroll_end(animate=False)
        except Exception:
            pass
        self.app.input.focus()
        self.app.set_timer(0, self.app._sync_ime_cursor)

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
        self.app.set_timer(0, self.app._sync_ime_cursor)

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
        self.app.thinking_label.update(f"⚠ {msg}")

    def print_error(self, msg: str) -> None:
        self.app._add_item("error", f"✖ {msg}")
        self.app.info_status.update("Status: error")

    def print_success(self, msg: str) -> None:
        self.app.thinking_label.update(f"✔ {msg}")


ITEMS = {
    "user": ("user-bubble", "message-user"),
    "assistant": ("assistant-bubble", "message-assistant"),
    "tool": ("tool-bubble", "message-tool"),
    "tool-result": ("tool-result-bubble", "message-tool-result"),
    "tool-error": ("tool-error-bubble", "message-tool-error"),
    "error": ("error-bubble", "message-error"),
}


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
            self.agent.ui = self.textual_ui_adapter
            if hasattr(self.agent, "loop") and self.agent.loop is not None:
                self.agent.loop.ui = self.textual_ui_adapter
        else:
            self.agent = Agent.from_settings()
            self.agent.ui = self.textual_ui_adapter
            if hasattr(self.agent, "loop") and self.agent.loop is not None:
                self.agent.loop.ui = self.textual_ui_adapter
        self.is_processing = False
        self.should_exit = False
        self._suggestions_active = False
        self._suggestions_readonly = False
        self._suggestion_commands: list[str] = []
        self.SUGGESTION_COMMANDS = ["/exit", "/quit", "/q", "/clear", "/help", "/skills", "/mcp"]
        self._activity_count = 0
        self._max_activities = 20
        self._agent_worker: Worker | None = None

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
        with ScrollableContainer(id="chat-area"), Vertical(id="chat-container"):
            pass
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

        kind ∈ {user, assistant, tool, tool-result, tool-error, error}
        """
        if kind not in ("user", "assistant"):
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

    # ── Input events ──

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._suggestions_active:
            self._suggestion_select()
            return
        text = event.value.strip()
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
        if cmd == "/clear":
            self._add_item("user", command)
            self.chat_container.remove_children()
            self._clear_activities()
            self._add_item(
                "assistant",
                "👋 Chat history cleared."
                " Ask me any programming question, and I'll do my best to help!",
            )
            self.thinking_label.update("Ready")
            self.info_status.update("Status: idle")
            self._update_context_info()
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
                "  /mcp    - List MCP server connection status\n"
                "  /skills - List available skills\n"
                "  /exit   - Exit the application\n"
                "  /quit   - Exit the application\n"
                "  /q      - Exit the application\n"
                "  /clear  - Clear chat history\n"
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
                skill = reg._skills.get(first_word)
                if skill is not None:
                    skill_content = skill["content"]
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
}
