"""Tests for utility functions."""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.utils.security import is_within, safe_resolve, sanitize_filename
from coding_agent.utils.tokens import count_tokens, estimate_messages_tokens
from coding_agent.utils.diff import generate_diff, generate_inline_diff


def test_safe_resolve_relative(tmp_path: Path) -> None:
    """测试相对路径解析。"""
    result = safe_resolve(tmp_path, "foo/bar.txt")
    assert result == (tmp_path / "foo" / "bar.txt").resolve()


def test_safe_resolve_absolute(tmp_path: Path) -> None:
    """测试绝对路径解析。"""
    abs_path = "/tmp/some/file.txt"
    result = safe_resolve(tmp_path, abs_path)
    assert result == Path(abs_path).resolve()


def test_is_within(tmp_path: Path) -> None:
    """测试路径包含检查。"""
    assert is_within(tmp_path / "sub" / "file.txt", tmp_path) is True
    assert is_within(Path("/other/path"), tmp_path) is False


def test_sanitize_filename() -> None:
    """测试文件名清理。"""
    assert sanitize_filename("normal.txt") == "normal.txt"
    assert sanitize_filename("a/b/c") == "a_b_c"
    assert sanitize_filename("../../etc/passwd") == "___etc_passwd"


def test_count_tokens() -> None:
    """测试 token 计数。"""
    # 英文
    assert count_tokens("hello world") > 0
    # 中文
    assert count_tokens("你好世界") > 0
    # 空字符串
    assert count_tokens("") == 0


def test_estimate_messages_tokens() -> None:
    """测试消息 token 估算。"""
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello!"},
    ]
    tokens = estimate_messages_tokens(messages)
    assert tokens > 0


def test_generate_diff() -> None:
    """测试 diff 生成。"""
    old = "line1\nline2\nline3"
    new = "line1\nchanged\nline3"
    diff = generate_diff(old, new, "test.txt")
    assert "-line2" in diff
    assert "+changed" in diff


def test_generate_inline_diff() -> None:
    """测试内联 diff。"""
    old = "a\nb\nc"
    new = "a\nB\nc"
    diff = generate_inline_diff(old, new)
    assert "- b" in diff
    assert "+ B" in diff
