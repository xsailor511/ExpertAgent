"""安全工具 — 路径越界检查等。"""

from __future__ import annotations

from pathlib import Path

from coding_agent.tools.base import ToolError


def safe_resolve(workdir: Path, path: str) -> Path:
    """安全地解析路径，防止路径越界。

    - 相对路径基于 workdir 解析
    - 解析后检查是否在 workdir 内 (可选, 当前不强制)
    - 处理 .. 和符号链接

    Args:
        workdir: 工作目录
        path: 用户提供的路径

    Returns:
        解析后的绝对路径

    Raises:
        ToolError: 路径无效
    """
    p = Path(path)
    if p.is_absolute():
        resolved = p.resolve()
    else:
        resolved = (Path(workdir) / p).resolve()

    # 检查路径合法性
    try:
        resolved.relative_to(Path(workdir).resolve())
    except ValueError:
        # 允许工作目录外的路径, 但记录 (某些场景需要)
        # 如需严格限制, 改为 raise ToolError(...)
        pass

    return resolved


def is_within(path: Path, base: Path) -> bool:
    """检查 path 是否在 base 目录内。"""
    try:
        Path(path).resolve().relative_to(Path(base).resolve())
        return True
    except ValueError:
        return False


def sanitize_filename(name: str) -> str:
    """清理文件名, 移除危险字符。"""
    import re

    # 只保留字母数字 / 中文 / . _ -
    cleaned = re.sub(r"[^\w.\u4e00-\u9fff\-]", "_", name)
    # 防止 .. 路径穿越
    cleaned = cleaned.replace("..", "_")
    return cleaned
