"""流式响应处理工具。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from coding_agent.llm.base import LLMResponse, StreamChunk, ToolCall


class StreamAggregator:
    """聚合流式 chunk，最终产出完整的 LLMResponse。

    用法:
        agg = StreamAggregator()
        async for chunk in llm.stream(...):
            agg.add(chunk)
            # 在这里实时渲染 chunk.content
        response = agg.finalize()
    """

    def __init__(self) -> None:
        self._content_parts: list[str] = []
        self._tool_calls: list[ToolCall] = []
        self._finish_reason: str = "stop"

    def add(self, chunk: StreamChunk) -> None:
        if chunk.content:
            self._content_parts.append(chunk.content)
        if chunk.tool_call:
            self._tool_calls.append(chunk.tool_call)
        if chunk.finish_reason:
            self._finish_reason = chunk.finish_reason

    def finalize(self) -> LLMResponse:
        return LLMResponse(
            content="".join(self._content_parts),
            tool_calls=list(self._tool_calls),
            finish_reason=self._finish_reason,
        )


async def collect_stream(stream: AsyncIterator[StreamChunk]) -> LLMResponse:
    """便捷函数：消费整个流并返回完整响应。"""
    agg = StreamAggregator()
    async for chunk in stream:
        agg.add(chunk)
    return agg.finalize()
