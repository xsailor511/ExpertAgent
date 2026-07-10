"""Modern TUI for Coding Agent - Built with Textual, similar to Claude Code."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Any, Dict, Optional

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.widgets import Button, Header, Input, Label, Static
from textual.binding import Binding

from coding_agent.core.agent import Agent
from coding_agent.ui.terminal import TerminalUI


class TextualUIAdapter(TerminalUI):
    """Textual UI adapter that captures streaming output and updates the TUI."""

    def __init__(self, app_instance: 'CodingAgentApp'):
        super().__init__()
        self.app = app_instance
        self._is_streaming = False
        self.assistant_bubble: Optional[Static] = None
        self.msg_wrapper: Optional[Container] = None
        self._bubble_created = False

    def _create_bubble_sync(self) -> None:
        """Create the assistant message bubble synchronously."""
        if self._bubble_created:
            return
        try:
            self.assistant_bubble = Static("", classes="assistant-bubble")
            self.msg_wrapper = Container(self.assistant_bubble, classes="message-wrapper message-assistant")
            
            # Get chat_container dynamically and mount
            chat_container = self.app.chat_container
            chat_container.mount(self.msg_wrapper)
            self._bubble_created = True
        except Exception as e:
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
        
        # Update the bubble text synchronously using update() method
        self.assistant_bubble.update(self._buffer)
        
        # Auto-scroll to bottom
        try:
            scroll_view = self.app.query_one("#chat-area", ScrollableContainer)
            scroll_view.scroll_end(animate=False)
        except Exception:
            pass

    def end_assistant_stream(self) -> None:
        self._is_streaming = False
        
        # Ensure the final text is displayed
        display_text = self._buffer if self._buffer else "(no content)"
        if self.assistant_bubble is not None:
            self.assistant_bubble.update(display_text)


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
        margin: 1 2 0 2;
        border: none;
        background: transparent;
    }

    #chat-container {
        padding: 1 1;
    }

    /* ----- Message containers ----- */
    .message-wrapper {
        width: 100%;
        margin: 1 0;
    }

    .message-user {
        align: right middle;
    }

    .message-assistant {
        align: left middle;
    }

    /* ----- Message bubbles ----- */
    .user-bubble {
        background: #313244;
        color: #cdd6f4;
        padding: 1 2;
        border: none;
        width: 80%;
    }

    .assistant-bubble {
        background: transparent;
        color: #cdd6f4;
        padding: 1 0;
        border: none;
        width: 80%;
    }

    /* ----- Input area ----- */
    #input-area {
        height: 3;
        margin: 0 2 1 2;
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

    #input-area Button {
        width: 12;
        background: #89b4fa;
        color: #1e1e2e;
        margin-left: 1;
        padding: 0 1;
        text-style: bold;
    }

    #input-area Button:hover {
        background: #74c7ec;
    }

    /* ----- Status bar ----- */
    #status {
        height: 1;
        background: #313244;
        color: #6c7086;
        padding: 0 2;
        dock: bottom;
    }

    /* ----- Header tweaks ----- */
    Header {
        background: #1e1e2e;
        color: #cdd6f4;
        padding: 0 2;
    }
    
    /* ----- Center mode (initial state) ----- */
    .is-center-mode #chat-area {
        height: auto;
        margin-top: 2;
        margin-bottom: 2;
    }

    .is-center-mode #input-area {
        margin: 0 2 4 2;
    }
    
    /* ----- Bottom mode (after typing starts) ----- */
    .is-bottom-mode #chat-area {
        height: 1fr;
        margin: 1 2 0 2;
    }

    .is-bottom-mode #input-area {
        margin: 0 2 1 2;
    }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
    ]

    def __init__(self, agent: Agent | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        
        # Create Textual UI adapter first
        self.textual_ui_adapter = TextualUIAdapter(self)
        
        if agent is not None:
            self.agent = agent
            # Replace the UI and loop UI with our Textual adapter
            self.agent.ui = self.textual_ui_adapter
            if hasattr(self.agent, 'loop') and self.agent.loop is not None:
                self.agent.loop.ui = self.textual_ui_adapter
        else:
            # Create agent from settings and replace UI
            self.agent = Agent.from_settings()
            # Replace the UI and loop UI with our Textual adapter
            self.agent.ui = self.textual_ui_adapter
            if hasattr(self.agent, 'loop') and self.agent.loop is not None:
                self.agent.loop.ui = self.textual_ui_adapter
                
        self.is_processing = False
        self.input_started = False
        self.should_exit = False

    def on_key(self, event: Key) -> None:
        """Handle key presses."""
        if self.should_exit:
            self.exit()

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield Header(show_clock=True)
        
        with ScrollableContainer(id="chat-area"):
            with Vertical(id="chat-container"):
                pass
        
        with Horizontal(id="input-area"):
            yield Input(placeholder="Ask me anything about coding...", id="input")
            yield Button("Send", id="send-btn")
        
        yield Label("Ready", id="status", classes="status")

    def on_mount(self) -> None:
        """Set up initial state and add welcome message."""
        self.chat_container = self.query_one("#chat-container", Vertical)
        self.input = self.query_one("#input", Input)
        self.status = self.query_one("#status", Label)

        # Add center mode class initially - input area positioned in the middle
        self.screen.add_class("is-center-mode")
        
        # Add welcome message
        self._add_message(
            "👋 Hello! I'm your AI coding assistant.\nAsk me any programming question, and I'll do my best to help!",
            is_user=False
        )
        self.status.update("Ready")
        self.input.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input changes - transition from center to bottom."""
        if not self.input_started and len(self.input.value) > 0:
            self.input_started = True
            # Remove center mode class and add bottom mode class
            self.screen.remove_class("is-center-mode")
            self.screen.add_class("is-bottom-mode")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission (Enter key pressed)."""
        text = event.value.strip()
        if not text or self.is_processing:
            return
        
        # Check for slash commands
        if text.startswith('/'):
            self._handle_slash_command(text)
        else:
            self.send_message()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press (Send button)."""
        if getattr(event.button, 'id', None) == "send-btn":
            text = self.input.value.strip()
            if not text or self.is_processing:
                return
            
            # Check for slash commands
            if text.startswith('/'):
                self._handle_slash_command(text)
            else:
                self.send_message()

    def _add_message(self, text: str, is_user: bool) -> None:
        """Add a message bubble to the chat area."""
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

    def _handle_slash_command(self, command: str) -> None:
        """Handle slash commands."""
        cmd = command.strip().lower()
        
        if cmd in ('/exit', '/quit', '/q'):
            # Clear input and quit the application
            self.input.value = ""
            # Call action_quit to exit the app properly
            self.action_quit()
            return
            
        elif cmd == '/clear':
            self._add_message(command, is_user=True)
            # Clear all messages from chat container
            self.chat_container.remove_children()
            # Add a new welcome message
            self._add_message(
                "👋 Chat history cleared. Ask me any programming question, and I'll do my best to help!",
                is_user=False
            )
            self.status.update("Ready")
            return
            
        elif cmd == '/help':
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
            self._add_message(f"Unknown command: '{command}'. Type /help for available commands.", is_user=False)
            return

    def send_message(self) -> None:
        """Send user message and trigger AI response."""
        text = self.input.value.strip()
        if not text or self.is_processing:
            return

        # Clear input and add user message
        self.input.value = ""
        self._add_message(text, is_user=True)
        self.status.update("🤔 Thinking...")
        self.is_processing = True

        # Process with agent using Textual worker system
        self.run_worker(self.process_agent_response(text))

    async def process_agent_response(self, user_text: str) -> None:
        """Process user text through the agent and add response."""
        try:
            # Run the agent's run method which is async - it will stream via TextualUIAdapter
            await self.agent.run(user_text)

            # Update status
            self.status.update("Ready")
        except Exception as e:
            self._add_message(f"Error: {str(e)}", is_user=False)
            self.status.update("❌ Error occurred")
        finally:
            self.is_processing = False
            
            # Auto-scroll to bottom after processing
            scroll_view = self.query_one("#chat-area", ScrollableContainer)
            scroll_view.scroll_end(animate=True)
