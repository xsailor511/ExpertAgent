"""日志配置 — 基于 loguru。"""

from __future__ import annotations

import sys
from typing import Optional

from loguru import logger as loguru_logger

# 移除默认 handler
loguru_logger.remove()


def setup_logging(level: str = "INFO", log_file: Optional[str] = None) -> None:
    """配置全局日志。

    Args:
        level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
        log_file: 日志文件路径 (可选)
    """
    # 控制台输出 (精简格式, 避免干扰 TUI)
    loguru_logger.add(
        sys.stderr,
        level=level,
        format="<dim>{time:HH:mm:ss}</dim> <level>{level:<7}</level> {message}",
        colorize=True,
    )

    # 文件输出 (完整格式)
    if log_file:
        loguru_logger.add(
            log_file,
            level="DEBUG",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {name}:{function}:{line} | {message}",
            rotation="10 MB",
            retention="7 days",
            encoding="utf-8",
        )


def get_logger(name: str = __name__):
    """获取命名 logger。"""
    return loguru_logger.bind(name=name)
