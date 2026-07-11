"""使用 Typer 的 CLI 入口点。"""

from __future__ import annotations

import asyncio
import importlib.resources
from pathlib import Path

import typer
from rich import print as rprint

from coding_agent.config import PermissionMode, SandboxType, get_settings

app = typer.Typer(
    name="coding-agent",
    help="一个基于 Python 的编码智能体。",
    no_args_is_help=False,
    add_completion=False,
    pretty_exceptions_enable=False,
)


_ENV_PATH = Path.home() / ".coding-agent" / ".env"


def _require_env() -> None:
    """检查 ~/.coding-agent/.env 是否存在，不存在则提示 init。"""
    if not _ENV_PATH.exists():
        rprint("[red]错误：[/] 未找到配置文件 ~/.coding-agent/.env")
        rprint("请先执行 [bold]coding-agent init[/] 初始化应用")
        raise typer.Exit(code=1)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    message: str | None = typer.Option(
        None, "-m", "--message", help="单次执行模式：直接传入消息，不进入交互"
    ),
    model: str | None = typer.Option(None, "--model", help="覆盖默认模型"),
    workdir: Path | None = typer.Option(None, "--workdir", "-C", help="工作目录"),
    permission: PermissionMode | None = typer.Option(None, "--permission", "-p", help="权限模式"),
    sandbox: SandboxType | None = typer.Option(None, "--sandbox", help="沙箱类型"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="详细日志"),
) -> None:
    """启动 coding agent。"""
    if ctx.invoked_subcommand is not None:
        return

    _require_env()
    settings = get_settings(env_file=_ENV_PATH)

    if model:
        settings.model = model
    if workdir:
        settings.workdir = workdir.resolve()
    if permission:
        settings.permission = permission
    if sandbox:
        settings.sandbox = sandbox

    if message:
        asyncio.run(_run_once(message))
    else:
        _run_textual_tui(settings)


async def _run_once(message: str) -> None:
    from coding_agent.core.agent import Agent

    agent = Agent.from_settings()
    await agent.run(message)
    await agent.close()


def _run_textual_tui(settings) -> None:
    """运行 Textual TUI 应用程序。"""
    from coding_agent.core.agent import Agent
    from coding_agent.ui.textual_app import CodingAgentApp

    agent = Agent.from_settings(settings)
    app_instance = CodingAgentApp(agent=agent)
    try:
        app_instance.run()
    except Exception as e:
        rprint(f"[red]运行 TUI 时出错: {e}[/]")
    finally:
        asyncio.run(agent.close())


@app.command()
def init() -> None:
    """初始化 ~/.coding-agent 配置目录。"""
    config_dir = Path.home() / ".coding-agent"
    config_dir.mkdir(parents=True, exist_ok=True)

    example_content = (
        importlib.resources.files("coding_agent").joinpath(".env.example").read_bytes()
    )
    dest = config_dir / ".env.example"
    if not dest.exists():
        dest.write_bytes(example_content)
        rprint(f"[bold green]OK[/] 已创建 [yellow]{dest}[/]")
    else:
        rprint(f"[dim]-- [yellow]{dest}[/] 已存在，跳过[/]")

    rprint(f"[bold green]OK[/] 已创建 [yellow]{config_dir}[/] 目录")
    rprint()
    rprint("[bold]下一步：[/]")
    rprint(f"  1. [cyan]cp {config_dir / '.env.example'} {config_dir / '.env'}[/]")
    rprint(f"  2. [cyan]编辑 {config_dir / '.env'}[/]，填入你的 API Key 等配置")
    rprint("  3. 运行 [bold]coding-agent[/] 启动 TUI")


if __name__ == "__main__":
    app()
