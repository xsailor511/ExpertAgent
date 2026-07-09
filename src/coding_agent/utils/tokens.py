"""Token 计数工具。"""

from __future__ import annotations

from typing import Any


def count_tokens(text: str, model: str = "gpt-4o") -> int:
    """估算文本的 token 数。

    优先使用 tiktoken (OpenAI 模型), 否则降级到字符数估算。
    """
    try:
        import tiktoken

        # gpt-4o 使用 o200k_base 编码
        if "gpt-4o" in model or "o1" in model:
            enc = tiktoken.get_encoding("o200k_base")
        else:
            enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        # 降级: 中文约 1 字 = 1 token, 英文约 4 字符 = 1 token
        cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        ascii_chars = len(text) - cjk
        return cjk + ascii_chars // 4


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """估算消息列表的总 token 数。

    每条消息约加 4 token 的开销 (role, separators)。
    """
    total = 0
    for msg in messages:
        content = msg.get("content", "") or ""
        total += count_tokens(content)
        total += 4  # 消息开销
        # tool_calls 的 token
        if "tool_calls" in msg:
            import json

            tc_text = json.dumps(msg["tool_calls"], ensure_ascii=False)
            total += count_tokens(tc_text)
    total += 2  # 结尾标记
    return total
