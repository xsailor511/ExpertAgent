"""权限策略 — 控制工具执行前的用户确认。"""

from __future__ import annotations

import json
from typing import Any

from coding_agent.config import PermissionMode
from coding_agent.ui.terminal import TerminalUI
from coding_agent.utils.logging import get_logger

log = get_logger(__name__)


class PermissionPolicy:
    """权限策略。

    模式:
        - ASK:     每次危险操作前询问
        - AUTO:    自动批准所有操作 (危险!)
        - READONLY: 拒绝所有写操作
    """

    # 需要确认的工具 (写操作 / 危险操作)
    DANGEROUS_TOOLS = {"write_file", "edit_file", "bash"}

    def __init__(self, mode: PermissionMode, ui: TerminalUI) -> None:
        self.mode = mode
        self.ui = ui

    async def check(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        description: str = "",
    ) -> bool:
        """检查是否允许执行该工具。"""
        # 只读模式: 拒绝所有危险工具
        if self.mode == PermissionMode.READONLY:
            if tool_name in self.DANGEROUS_TOOLS:
                self.ui.print_warning(
                    f"只读模式：已阻止 {tool_name}"
                )
                return False
            return True

        # 自动模式: 全部放行
        if self.mode == PermissionMode.AUTO:
            return True

        # 询问模式: 危险工具需确认
        if tool_name not in self.DANGEROUS_TOOLS:
            return True

        return await self._ask_user(tool_name, arguments, description)

    async def _ask_user(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        description: str,
    ) -> bool:
        """向用户确认。"""
        # 构造提示
        args_str = json.dumps(arguments, ensure_ascii=False, indent=2)
        prompt = (
            f"\n[bold yellow]⚠ {tool_name}[/] 想要运行:\n"
            f"[dim]{args_str}[/]\n"
            f"是否允许？"
        )
        self.ui.console.print(prompt)
        # 同步确认 (在交互场景下可接受)
        import anyio

        approved = await anyio.to_thread.run_sync(
            lambda: self.ui.confirm("执行?", default=False)
        )
        if approved:
            log.info(f"用户已批准 {tool_name}")
        else:
            log.info(f"用户已拒绝 {tool_name}")
        return approved
