"""日志配置 — 基于 loguru。"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger as loguru_logger

# 移除默认 handler
loguru_logger.remove()


def setup_logging(level: str = "INFO", log_file: str | None = None) -> None:
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
        log_file = Path(log_file)
        # 容错: 若给的是目录, 自动补默认文件名
        if log_file.is_dir():
            log_file = log_file / "coding-agent.log"
        try:
            loguru_logger.add(
                log_file,
                level="DEBUG",
                format=(
                    "{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | "
                    "{name}:{function}:{line} | {message}"
                ),
                rotation="10 MB",
                retention="7 days",
                encoding="utf-8",
            )
        except Exception as e:
            # 文件日志失败不应阻断启动, 仅退回控制台日志
            loguru_logger.warning(
                f"文件日志初始化失败, 仅使用控制台日志: {e}"
            )


def get_logger(name: str = __name__):
    """获取命名 logger。"""
    return loguru_logger.bind(name=name)
