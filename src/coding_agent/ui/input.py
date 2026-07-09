"""交互式输入处理。"""

from __future__ import annotations

import asyncio
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console


class InputHandler:
    """多行输入处理器。

    支持:
        - 多行输入 (以 \ 结尾续行)
        - 输入历史
        - 异步读取
    """

    def __init__(self) -> None:
        self.console = Console()
        self.history = InMemoryHistory()
        self.session: Optional[PromptSession] = None

    async def read(self, prompt: str = "❯ ") -> str:
        """读取用户输入 (支持多行)。"""
        if self.session is None:
            self.session = PromptSession(history=self.history)

        # prompt_toolkit 是同步的, 用 anyio 包装
        import anyio

        # 多行输入: 以 \ 结尾时继续读取
        lines: list[str] = []
        current_prompt = prompt
        while True:
            try:
                line = await anyio.to_thread.run_sync(
                    self.session.prompt, current_prompt
                )
            except (EOFError, KeyboardInterrupt):
                raise

            # 去掉末尾反斜杠续行
            if line.endswith("\\"):
                lines.append(line[:-1])
                current_prompt = "  "  # 续行缩进
                continue
            lines.append(line)
            break

        return "\n".join(lines)
