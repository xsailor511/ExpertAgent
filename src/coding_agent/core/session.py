"""会话状态管理。"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from coding_agent.utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class SessionState:
    """会话状态快照。"""

    session_id: str
    workdir: Path
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    turn_count: int = 0
    tool_call_count: int = 0
    total_tokens: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class Session:
    """单次会话管理。

    负责跟踪会话元数据、状态快照、(可选)持久化。
    """

    def __init__(self, workdir: Path, session_id: str | None = None) -> None:
        self.state = SessionState(
            session_id=session_id or str(uuid.uuid4())[:8],
            workdir=Path(workdir),
        )
        log.info(f"会话已启动: {self.state.session_id} (工作目录={workdir})")

    def record_turn(self, tokens: int = 0) -> None:
        """记录一轮对话。"""
        self.state.turn_count += 1
        self.state.total_tokens += tokens
        self.state.updated_at = time.time()

    def record_tool_call(self) -> None:
        """记录一次工具调用。"""
        self.state.tool_call_count += 1
        self.state.updated_at = time.time()

    def summary(self) -> str:
        """生成会话摘要。"""
        return (
            f"会话 {self.state.session_id}: "
            f"{self.state.turn_count} 轮对话, "
            f"{self.state.tool_call_count} 次工具调用, "
            f"{self.state.total_tokens} tokens"
        )

    async def close(self) -> None:
        """关闭会话。"""
        log.info(f"会话已关闭: {self.summary()}")
