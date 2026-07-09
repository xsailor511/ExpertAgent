"""CLI entry point using Typer."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint

from coding_agent.config import PermissionMode, SandboxType, get_settings

app = typer.Typer(
    name="coding-agent",
    help="A Python-based coding agent.",
    no_args_is_help=False,
    add_completion=False,
)


@app.command()
def chat(
    message: Optional[str] = typer.Option(
        None, "-m", "--message", help="单次执行模式：直接传入消息，不进入交互"
    ),
    model: Optional[str] = typer.Option(None, "--model", help="覆盖默认模型"),
    workdir: Optional[Path] = typer.Option(None, "--workdir", "-C", help="工作目录"),
    permission: Optional[PermissionMode] = typer.Option(
        None, "--permission", "-p", help="权限模式"
    ),
    sandbox: Optional[SandboxType] = typer.Option(None, "--sandbox", help="沙箱类型"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="详细日志"),
) -> None:
    """启动 coding agent。"""
    settings = get_settings()

    # 命令行参数覆盖配置
    if model:
        settings.model = model
    if workdir:
        settings.workdir = workdir.resolve()
    if permission:
        settings.permission = permission
    if sandbox:
        settings.sandbox = sandbox

    rprint(f"[bold cyan]coding-agent[/] v0.1.0")
    rprint(f"  model:      [yellow]{settings.model}[/]")
    rprint(f"  workdir:    [yellow]{settings.workdir}[/]")
    rprint(f"  permission: [yellow]{settings.permission.value}[/]")
    rprint(f"  sandbox:    [yellow]{settings.sandbox.value}[/]")
    rprint()

    try:
        if message:
            # 单次模式
            asyncio.run(_run_once(message))
        else:
            # 交互模式
            asyncio.run(_run_interactive())
    except KeyboardInterrupt:
        rprint("\n[dim]Bye 👋[/]")


async def _run_once(message: str) -> None:
    from coding_agent.core.agent import Agent

    agent = Agent.from_settings()
    await agent.run(message)
    await agent.close()


async def _run_interactive() -> None:
    from coding_agent.core.agent import Agent
    from coding_agent.ui.input import InputHandler

    agent = Agent.from_settings()
    input_handler = InputHandler()

    rprint("[dim]输入你的需求，Ctrl+C 退出。输入 /help 查看命令[/]\n")

    while True:
        try:
            user_input = await input_handler.read()
            if not user_input.strip():
                continue

            # 内置命令
            if user_input.strip() == "/help":
                _print_help()
                continue
            if user_input.strip() in ("/exit", "/quit", "/q"):
                break
            if user_input.strip() == "/clear":
                agent.clear_history()
                rprint("[dim]历史已清空[/]\n")
                continue

            await agent.run(user_input)
        except (KeyboardInterrupt, EOFError):
            break

    await agent.close()
    rprint("[dim]Bye 👋[/]")


def _print_help() -> None:
    rprint("\n[bold]命令:[/]")
    rprint("  [cyan]/help[/]    显示帮助")
    rprint("  [cyan]/clear[/]  清空对话历史")
    rprint("  [cyan]/exit[/]   退出")
    rprint()


if __name__ == "__main__":
    app()
