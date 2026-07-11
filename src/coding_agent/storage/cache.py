"""LLM 响应缓存。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from coding_agent.utils.logging import get_logger

log = get_logger(__name__)


class ResponseCache:
    """LLM 响应缓存 (基于文件)。

    用于缓存相同请求的响应, 节省 API 调用。
    生产环境建议替换为 Redis。
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        if base_dir is None:
            base_dir = Path.home() / ".coding_agent" / "cache"
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, model: str, messages: list[dict[str, Any]], **kwargs: Any) -> str:
        """生成缓存 key。"""
        payload = json.dumps(
            {"model": model, "messages": messages, **kwargs},
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def get(self, model: str, messages: list[dict[str, Any]], **kwargs: Any) -> Any | None:
        """读取缓存。"""
        key = self._key(model, messages, **kwargs)
        path = self.base_dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def set(
        self, model: str, messages: list[dict[str, Any]], response: Any, **kwargs: Any
    ) -> None:
        """写入缓存。"""
        key = self._key(model, messages, **kwargs)
        path = self.base_dir / f"{key}.json"
        try:
            path.write_text(
                json.dumps(response, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            log.warning(f"Failed to write cache: {e}")

    def clear(self) -> None:
        """清空缓存。"""
        for p in self.base_dir.glob("*.json"):
            p.unlink()
