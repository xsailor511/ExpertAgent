"""Modern TUI for Coding Agent - Built with Textual, similar to Claude Code."""

from __future__ import annotations

import os
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.events import Key
from textual.widgets import Button, Header, Input, Label, ListItem, ListView, Static

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


class TextualUIAdapter(TerminalUI):
    """Textual UI adapter that captures streaming output and updates the TUI."""

    def __init__(self, app_instance: CodingAgentApp):
        super().__init__()
        self.app = app_instance
        self._is_streaming = False
        self.assistant_bubble: Static | None = None
        self.msg_wrapper: Container | None = None
        self._bubble_created = False

    def _create_bubble_sync(self) -> None:
        """Create the assistant message bubble synchronously."""
        if self._bubble_created:
            return
        try:
            self.assistant_bubble = Static("", classes="assistant-bubble")
            self.msg_wrapper = Container(
                self.assistant_bubble, classes="message-wrapper message-assistant"
            )

            # Get chat_container dynamically and mount
            chat_container = self.app.chat_container
            chat_container.mount(self.msg_wrapper)
            self._bubble_created = True
        except Exception:
            pass

    def start_assistant_stream(self) -> None:
        self._buffer = ""
        self._is_streaming = True

        # Create the bubble synchronously
        self._create_bubble_sync()

    def update_assistant_stream(self, chunk: str) -> None:
        if not self._is_streaming:
            return

        # Ensure bubble is created
        if not self._bubble_created:
            self._create_bubble_sync()

        if self.assistant_bubble is None:
            return

        # Update the buffer
        self._buffer = (self._buffer or "") + chunk

        # Update the bubble text
        self.assistant_bubble.update(self._buffer)
        # Force layout recalculation so the bubble resizes with content
        self.assistant_bubble.refresh(layout=True)

        # Auto-scroll to bottom
        try:
            scroll_view = self.app.query_one("#chat-area", ScrollableContainer)
            scroll_view.scroll_end(animate=False)
        except Exception:
            pass

        # Re-focus + sync IME composition window after render cycle completes
        self.app.input.focus()
        self.app.set_timer(0, self.app._sync_ime_cursor)

    def end_assistant_stream(self) -> None:
        self._is_streaming = False

        # Ensure the final text is displayed
        display_text = self._buffer if self._buffer else "(no content)"
        if self.assistant_bubble is not None:
            self.assistant_bubble.update(display_text)
            self.assistant_bubble.refresh(layout=True)

        # Re-focus + sync IME composition window after render cycle completes
        self.app.input.focus()
        self.app.set_timer(0, self.app._sync_ime_cursor)


class CodingAgentApp(App):
    """Main TUI application class - Claude Code style."""

    CSS = """
    /* ----- Global styles ----- */
    Screen {
        background: #1e1e2e;
    }

    /* ----- Chat area ----- */
    #chat-area {
        height: 1fr;
        margin: 1 2;
        border: none;
        background: transparent;
    }

    #chat-container {
        padding: 1 1;
        height: auto;
    }

    /* ----- Message containers ----- */
    .message-wrapper {
        width: 100%;
        margin: 1 0;
        height: auto;
    }

    .message-user {
        align: left middle;
        height: auto;
    }

    .message-assistant {
        align: left middle;
        height: auto;
    }

    /* ----- Message bubbles ----- */
    .user-bubble {
        background: transparent;
        color: #89b4fa;
        padding: 1 1;
        border-left: solid #89b4fa;
        width: 100%;
        height: auto;
    }

    .assistant-bubble {
        background: transparent;
        color: #cdd6f4;
        padding: 1 1;
        border-left: solid #a6e3a1;
        width: 100%;
        height: auto;
        min-height: 1;
    }

    /* ----- Input area ----- */
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

    /* ----- Bottom: thinking status + suggestions + input + info row ----- */
    #thinking-label {
        height: 1;
        margin: 0 2 1 2;
        color: #a6adc8;
        padding: 0;
    }

    #suggestion-list {
        display: none;
        height: auto;
        max-height: 6;
        margin: 0 2;
        background: #181825;
        border: tall #45475a;
        padding: 0;
    }

    #suggestion-list > .list-view--highlighted {
        background: #313244;
    }

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

    /* ----- Header tweaks ----- */
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

        # Create Textual UI adapter first
        self.textual_ui_adapter = TextualUIAdapter(self)

        if agent is not None:
            self.agent = agent
            # Replace the UI and loop UI with our Textual adapter
            self.agent.ui = self.textual_ui_adapter
            if hasattr(self.agent, "loop") and self.agent.loop is not None:
                self.agent.loop.ui = self.textual_ui_adapter
        else:
            # Create agent from settings and replace UI
            self.agent = Agent.from_settings()
            # Replace the UI and loop UI with our Textual adapter
            self.agent.ui = self.textual_ui_adapter
            if hasattr(self.agent, "loop") and self.agent.loop is not None:
                self.agent.loop.ui = self.textual_ui_adapter

        self.is_processing = False
        self.should_exit = False
        self._suggestions_active = False
        self._suggestion_commands: list[str] = []
        self.SUGGESTION_COMMANDS = ["/exit", "/quit", "/q", "/clear", "/help"]

    def _update_context_info(self) -> None:
        """Refresh the context usage info label."""
        try:
            memory = self.agent.memory
            used = memory.token_count()
            limit = getattr(memory, "max_tokens", 0) or 0
            self.info_context.update(f"Context: {used}/{limit}")
        except Exception:
            pass

    def _sync_ime_cursor(self) -> None:
        """Set Windows IME composition window to follow the Input widget cursor position."""
        if os.name != "nt":
            return
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            imm32 = ctypes.windll.imm32

            # Position within the Input widget (accounting for border)
            col = self.input.region.x + 1
            row = self.input.region.y + 1

            # 1) Move console cursor so the terminal knows where we are
            con_out = kernel32.GetStdHandle(-11)
            packed = ctypes.c_uint32(col | (row << 16))
            kernel32.SetConsoleCursorPosition(con_out, packed)

            # 2) Move the IME composition window to the same cell (in pixels).
            #    Approximate: 1 cell ≈ 8×16 px; the IME only needs to be in the
            #    right ballpark — the exact font metrics aren't critical.
            hwnd = kernel32.GetConsoleWindow()
            if hwnd:
                himc = imm32.ImmGetContext(hwnd)
                if himc:
                    # COMPOSITIONFORM: { dwStyle, ptCurrentPos }
                    style = ctypes.c_uint32(1)  # CFS_POINT
                    pt_x = ctypes.c_int32(col * 8)
                    pt_y = ctypes.c_int32(row * 16)
                    buf = (ctypes.c_uint32 * 3)(style.value, pt_x.value, pt_y.value)
                    imm32.ImmSetCompositionWindow(himc, buf)
                    imm32.ImmReleaseContext(hwnd, himc)
        except Exception:
            pass

    def on_key(self, event: Key) -> None:
        """Handle key presses."""
        if self.should_exit:
            self.exit()

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield Header(show_clock=True)

        with ScrollableContainer(id="chat-area"), Vertical(id="chat-container"):
            pass

        yield Label("Ready", id="thinking-label")
        yield ListView(id="suggestion-list")
        with Horizontal(id="input-area"):
            yield CompletableInput(placeholder="Ask me anything about coding...", id="input")

        with Horizontal(id="info-row"):
            yield Label("───", id="info-status", classes="info-cell")
            yield Label("───", id="info-model", classes="info-cell")
            yield Label("───", id="info-context", classes="info-cell")

    def on_mount(self) -> None:
        """Set up initial state and add welcome message."""
        self.chat_container = self.query_one("#chat-container", Vertical)
        self.input = self.query_one("#input", Input)
        self.thinking_label = self.query_one("#thinking-label", Label)
        self.info_status = self.query_one("#info-status", Label)
        self.info_model = self.query_one("#info-model", Label)
        self.info_context = self.query_one("#info-context", Label)

        # Populate model name
        try:
            model = getattr(self.agent.llm, "model", None) or "───"
            self.info_model.update(f"Model: {model}")
        except Exception:
            pass

        # Populate context info
        self._update_context_info()

        # Add welcome message
        self._add_message(
            "👋 Hello! I'm your AI coding assistant."
            "\nAsk me any programming question, and I'll do my best to help!",
            is_user=False,
        )
        self.thinking_label.update("Ready")
        self.info_status.update("Status: idle")
        self.input.focus()
        self._sync_ime_cursor()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission (Enter key pressed)."""
        if self._suggestions_active:
            self._suggestion_select()
            return
        text = event.value.strip()
        if not text or self.is_processing:
            return

        # Check for slash commands
        if text.startswith("/"):
            self._handle_slash_command(text)
        else:
            self.send_message()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press (Send button)."""
        if getattr(event.button, "id", None) == "send-btn":
            text = self.input.value.strip()
            if not text or self.is_processing:
                return

            # Check for slash commands
            if text.startswith("/"):
                self._handle_slash_command(text)
            else:
                self.send_message()

    def _add_message(self, text: str, is_user: bool) -> None:
        """Add a message bubble to the chat area."""

        # Handle tabs in text
        if "\t" in text:
            text = text.expandtabs()

        if is_user:
            bubble = Static(text, classes="user-bubble")
            msg_wrapper = Container(bubble, classes="message-wrapper message-user")
        else:
            bubble = Static(text, classes="assistant-bubble")
            msg_wrapper = Container(bubble, classes="message-wrapper message-assistant")

        self.chat_container.mount(msg_wrapper)

        # Auto-scroll to bottom
        scroll_view = self.query_one("#chat-area", ScrollableContainer)
        scroll_view.scroll_end(animate=False)

    def action_quit(self) -> None:
        """Quit the application."""
        self.exit()

    def action_send_message_action(self) -> None:
        """Send user message and trigger AI response."""
        if self._suggestions_active:
            self._suggestion_select()
        text = self.input.value.strip()
        if not text or self.is_processing:
            return

        # Check for slash commands
        if text.startswith("/"):
            self._handle_slash_command(text)
        else:
            self.send_message()

    def action_clear_input_action(self) -> None:
        """Clear the input field."""
        self.input.value = ""

    def _handle_slash_command(self, command: str) -> None:
        """Handle slash commands."""
        cmd = command.strip().lower()

        if cmd in ("/exit", "/quit", "/q"):
            # Clear input and quit the application
            self.input.value = ""
            # Call action_quit to exit the app properly
            self.action_quit()
            return

        elif cmd == "/clear":
            self._add_message(command, is_user=True)
            # Clear all messages from chat container
            self.chat_container.remove_children()
            # Add a new welcome message
            self._add_message(
                "👋 Chat history cleared."
                " Ask me any programming question, and I'll do my best to help!",
                is_user=False,
            )
            self.thinking_label.update("Ready")
            self.info_status.update("Status: idle")
            self._update_context_info()
            return

        elif cmd == "/help":
            self._add_message(command, is_user=True)
            help_text = (
                "Available commands:\n"
                "  /exit   - Exit the application\n"
                "  /quit   - Exit the application\n"
                "  /q      - Exit the application\n"
                "  /clear  - Clear chat history\n"
                "  /help   - Show this help message"
            )
            self._add_message(help_text, is_user=False)
            return

        else:
            # Unknown command, treat as regular message or show error
            self._add_message(command, is_user=True)
            self._add_message(
                f"Unknown command: '{command}'. Type /help for available commands.",
                is_user=False,
            )
            return

    def on_input_changed(self, event: Input.Changed) -> None:
        """Show suggestions when the user types /."""
        value = event.value
        if value.startswith("/"):
            # If the value is an exact command match, hide popup
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

    def _show_suggestions(self, commands: list[str]) -> None:
        self._suggestion_commands = commands
        sv = self.query_one("#suggestion-list", ListView)
        sv.clear()
        for cmd in commands:
            sv.append(ListItem(Label(cmd)))
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
            sv.index = sv.index - 1

    def _suggestion_next(self) -> None:
        sv = self.query_one("#suggestion-list", ListView)
        if not sv.children:
            return
        if sv.index is None:
            sv.index = 0
        else:
            sv.index = (sv.index + 1) % len(sv.children)

    def _suggestion_select(self) -> None:
        sv = self.query_one("#suggestion-list", ListView)
        if sv.index is not None and sv.index < len(self._suggestion_commands):
            cmd = self._suggestion_commands[sv.index]
            self.input.value = cmd
            self.input.cursor_position = len(cmd)
        self._hide_suggestions()

    def send_message(self) -> None:
        """Send user message and trigger AI response."""
        text = self.input.value.strip()
        if not text or self.is_processing:
            return

        # Clear input and add user message
        self.input.value = ""
        self._add_message(text, is_user=True)
        self.thinking_label.update("🤔 Thinking...")
        self.info_status.update("Status: streaming")
        self.is_processing = True

        # Process with agent using Textual worker system
        self.run_worker(self.process_agent_response(text))

    async def process_agent_response(self, user_text: str) -> None:
        """Process user text through the agent and add response."""
        try:
            # Run the agent's run method which is async - it will stream via TextualUIAdapter
            await self.agent.run(user_text)

            self.thinking_label.update("Ready")
            self.info_status.update("Status: idle")
        except Exception as e:
            self._add_message(f"Error: {str(e)}", is_user=False)
            self.thinking_label.update("❌ Error occurred")
            self.info_status.update("Status: error")
        finally:
            self.is_processing = False

            self._update_context_info()

            # Auto-scroll to bottom after processing
            scroll_view = self.query_one("#chat-area", ScrollableContainer)
            scroll_view.scroll_end(animate=True)
