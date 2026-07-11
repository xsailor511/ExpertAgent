"""Diff 生成工具。"""

from __future__ import annotations

import difflib


def generate_diff(old_text: str, new_text: str, filename: str | None = None) -> str:
    """生成 unified diff。"""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)

    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{filename}" if filename else "old",
        tofile=f"b/{filename}" if filename else "new",
    )
    return "".join(diff)


def generate_inline_diff(old_text: str, new_text: str) -> str:
    """生成简易行级 diff (用于显示)。"""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    result: list[str] = []

    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            for line in old_lines[i1:i2]:
                result.append(f"  {line}")
        elif op == "replace":
            for line in old_lines[i1:i2]:
                result.append(f"- {line}")
            for line in new_lines[j1:j2]:
                result.append(f"+ {line}")
        elif op == "delete":
            for line in old_lines[i1:i2]:
                result.append(f"- {line}")
        elif op == "insert":
            for line in new_lines[j1:j2]:
                result.append(f"+ {line}")

    return "\n".join(result)
