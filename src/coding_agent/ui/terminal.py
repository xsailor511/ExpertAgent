"""终端 UI — 基于 Rich 的渲染管理。"""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text


class TerminalUI:
    """终端 UI 控制器。

    负责所有终端输出:
        - 用户输入回显
        - LLM 流式响应渲染 (Markdown)
        - 工具调用与结果展示
        - 错误 / 警告 / 信息提示
    """

    def __init__(self) -> None:
        self.console = Console()
        self._live: Live | None = None
        self._buffer: str = ""

    # === 用户输入 ===

    def print_user(self, text: str) -> None:
        self.console.print(
            Panel(Text(text, style="bold"), title="[bold blue]你[/]", border_style="blue")
        )

    # === LLM 流式输出 ===

    def start_assistant_stream(self) -> None:
        self._buffer = ""
        self._live = Live(
            Panel(Markdown(""), title="[bold green]智能体[/]", border_style="green"),
            console=self.console,
            refresh_per_second=15,
            transient=False,
        )
        self._live.start()

    def update_assistant_stream(self, chunk: str) -> None:
        if self._live is None:
            return
        self._buffer += chunk
        self._live.update(
            Panel(
                Markdown(self._buffer),
                title="[bold green]智能体[/]",
                border_style="green",
            )
        )

    def end_assistant_stream(self) -> None:
        if self._live is not None:
            self._live.update(
                Panel(
                    Markdown(self._buffer) if self._buffer else Text("(无内容)", style="dim"),
                    title="[bold green]智能体[/]",
                    border_style="green",
                )
            )
            self._live.stop()
            self._live = None
        self._buffer = ""

    def print_assistant_done(self) -> None:
        self.console.print()  # 空行分隔

    # === 工具调用 ===

    def print_tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        args_str = json.dumps(arguments, ensure_ascii=False, indent=2)
        syntax = Syntax(args_str, "json", theme="monokai", word_wrap=True)
        self.console.print(
            Panel(
                syntax,
                title=f"[bold yellow]🔧 {name}[/]",
                border_style="yellow",
                padding=(0, 1),
            )
        )

    def print_tool_result(
        self, name: str, result: str, *, is_error: bool = False
    ) -> None:
        style = "red" if is_error else "cyan"
        icon = "❌" if is_error else "✅"
        # 截断过长结果
        display = result
        if len(display) > 2000:
            display = display[:2000] + f"\n... (共 {len(result)} 字符，已截断)"
        self.console.print(
            Panel(
                Text(display, style=style),
                title=f"[{style}]{icon} {name} 结果[/]",
                border_style=style,
                padding=(0, 1),
            )
        )

    def print_tool_error(
        self, name: str, arguments: dict[str, Any], error: str
    ) -> None:
        self.console.print(
            Panel(
                Text(error, style="bold red"),
                title=f"[bold red]❌ {name} 错误[/]",
                border_style="red",
            )
        )

    def print_tool_rejected(self, name: str, arguments: dict[str, Any]) -> None:
        self.console.print(
            Panel(
                Text("用户拒绝了此工具调用。", style="yellow"),
                title=f"[yellow]🚫 {name} 被拒绝[/]",
                border_style="yellow",
            )
        )

    # === SubAgent 可视化（轻量日志模式）===

    def print_subagent_start(self, description: str) -> None:
        self.console.print(
            Panel(
                Text(description, style="bold"),
                title="[bold magenta]🔄 SubAgent[/]",
                border_style="magenta",
            )
        )

    def print_subagent_milestone(self, msg: str) -> None:
        self.console.print(f"  [dim]· {msg}[/]")

    def print_subagent_end(self, summary: str) -> None:
        if not summary:
            summary = "(no output)"
        self.console.print(
            Panel(
                Text(summary, style="green"),
                title="[bold green]✅ SubAgent 完成[/]",
                border_style="green",
            )
        )

    # === Teammate 可视化（事件驱动）===

    def print_teammate_progress(self, name: str, msg: str) -> None:
        self.console.print(f"  [dim gold3][{name}] {msg}[/]")

    def print_teammate_complete(self, name: str, msg: str) -> None:
        self.console.print(
            Panel(
                Text(msg, style="bold"),
                title=f"[bold gold3]✅ {name}[/]",
                border_style="gold3",
            )
        )

    # 保留旧别名保证向后兼容
    def print_teammate_event(self, name: str, msg: str) -> None:
        self.print_teammate_complete(name, msg)

    # === 通用消息 ===

    def print_info(self, msg: str) -> None:
        self.console.print(f"[dim]{msg}[/]")

    def print_warning(self, msg: str) -> None:
        self.console.print(f"[yellow]⚠ {msg}[/]")

    def print_error(self, msg: str) -> None:
        self.console.print(f"[red]✖ {msg}[/]")

    def print_success(self, msg: str) -> None:
        self.console.print(f"[green]✔ {msg}[/]")

    # === 用户确认 ===

    def confirm(self, prompt: str, default: bool = False) -> bool:
        """同步确认对话框。"""
        suffix = " [Y/n]: " if default else " [y/N]: "
        try:
            answer = input(prompt + suffix).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if not answer:
            return default
        return answer in ("y", "yes")
