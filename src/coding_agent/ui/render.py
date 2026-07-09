"""Markdown / 代码块渲染工具。"""

from __future__ import annotations

from typing import Optional

from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text


def render_markdown(text: str) -> Markdown:
    """渲染 Markdown。"""
    return Markdown(text)


def render_code(code: str, language: str = "python") -> Syntax:
    """渲染代码块。"""
    return Syntax(code, language, theme="monokai", line_numbers=True, word_wrap=True)


def render_diff(diff_text: str) -> Text:
    """渲染 diff (简单着色)。"""
    text = Text()
    for line in diff_text.splitlines():
        if line.startswith("+"):
            text.append(line + "\n", style="green")
        elif line.startswith("-"):
            text.append(line + "\n", style="red")
        elif line.startswith("@@"):
            text.append(line + "\n", style="cyan")
        else:
            text.append(line + "\n", style="white")
    return text


def truncate(text: str, max_chars: int = 2000, suffix: Optional[str] = None) -> str:
    """截断过长文本。"""
    if len(text) <= max_chars:
        return text
    suffix = suffix or f"\n... ({len(text)} chars total, truncated)"
    return text[:max_chars] + suffix
