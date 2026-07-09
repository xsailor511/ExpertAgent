"""对话历史持久化。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from coding_agent.utils.logging import get_logger

log = get_logger(__name__)


class HistoryStore:
    """对话历史存储 (JSON 文件)。

    存储路径: ~/.coding_agent/history/{session_id}.json
    """

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        if base_dir is None:
            base_dir = Path.home() / ".coding_agent" / "history"
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        """保存对话历史。"""
        path = self.base_dir / f"{session_id}.json"
        try:
            path.write_text(
                json.dumps(messages, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log.debug(f"Saved history to {path}")
        except Exception as e:
            log.error(f"Failed to save history: {e}")

    def load(self, session_id: str) -> Optional[list[dict[str, Any]]]:
        """加载对话历史。"""
        path = self.base_dir / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log.error(f"Failed to load history: {e}")
            return None

    def list_sessions(self) -> list[str]:
        """列出所有会话 ID。"""
        return [p.stem for p in self.base_dir.glob("*.json")]

    def delete(self, session_id: str) -> None:
        """删除会话历史。"""
        path = self.base_dir / f"{session_id}.json"
        if path.exists():
            path.unlink()
