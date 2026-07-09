"""路径处理工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def relative_to(path: Path, base: Path) -> str:
    """获取相对路径字符串, 失败则返回绝对路径。"""
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path)


def ensure_dir(path: Path) -> Path:
    """确保目录存在。"""
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_text_file(path: Path, sample_size: int = 8192) -> bool:
    """判断文件是否为文本文件。"""
    try:
        with open(path, "rb") as f:
            sample = f.read(sample_size)
        # 简单启发式: 不含 NULL 字节视为文本
        return b"\x00" not in sample
    except Exception:
        return False


def get_file_info(path: Path) -> dict:
    """获取文件信息。"""
    stat = path.stat()
    return {
        "path": str(path),
        "size": stat.st_size,
        "is_dir": path.is_dir(),
        "is_file": path.is_file(),
        "modified": stat.st_mtime,
    }
