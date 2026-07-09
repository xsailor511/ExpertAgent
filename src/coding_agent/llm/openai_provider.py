"""OpenAI 兼容的 LLM Provider (支持 OpenAI / 智谱 / 各种兼容接口)。"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional

from coding_agent.llm.base import (
    LLMProvider,
    LLMResponse,
    Message,
    StreamChunk,
    ToolCall,
)
from coding_agent.utils.logging import get_logger

log = get_logger(__name__)


class OpenAIProvider(LLMProvider):
    """基于 openai SDK 的 Provider，兼容所有 OpenAI 协议接口。"""

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(model, api_key, base_url, **kwargs)
        # 延迟导入，避免未安装时报错
        from openai import AsyncOpenAI

        client_kwargs: dict[str, Any] = {}
        if api_key:
            client_kwargs["api_key"] = api_key
        if base_url:
            client_kwargs["base_url"] = base_url

        self.client = AsyncOpenAI(**client_kwargs)

    async def chat(
        self,
        messages: list[Message],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        kwargs = self._build_kwargs(messages, tools, temperature, max_tokens, stream=False)
        response = await self.client.chat.completions.create(**kwargs)
        return self._parse_response(response)

    async def stream(
        self,
        messages: list[Message],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[StreamChunk]:
        kwargs = self._build_kwargs(messages, tools, temperature, max_tokens, stream=True)
        response = await self.client.chat.completions.create(**kwargs)

        # 累积 tool_calls (流式中分片到达)
        tool_calls_acc: dict[int, dict[str, Any]] = {}

        async for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            finish = chunk.choices[0].finish_reason

            # 文本内容
            content = delta.content or ""
            if content:
                yield StreamChunk(content=content)

            # 工具调用 (流式分片)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {
                            "id": tc.id or "",
                            "name": "",
                            "arguments": "",
                        }
                    if tc.id:
                        tool_calls_acc[idx]["id"] = tc.id
                    if tc.function and tc.function.name:
                        tool_calls_acc[idx]["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        tool_calls_acc[idx]["arguments"] += tc.function.arguments

            if finish:
                # 流结束，输出累积的 tool_calls
                for acc in tool_calls_acc.values():
                    try:
                        args = json.loads(acc["arguments"]) if acc["arguments"] else {}
                    except json.JSONDecodeError:
                        args = {"_raw": acc["arguments"]}
                    yield StreamChunk(
                        tool_call=ToolCall(id=acc["id"], name=acc["name"], arguments=args),
                        finish_reason=finish,
                    )
                if not tool_calls_acc:
                    yield StreamChunk(finish_reason=finish)

    def _build_kwargs(
        self,
        messages: list[Message],
        tools: Optional[list[dict[str, Any]]],
        temperature: float,
        max_tokens: Optional[int],
        stream: bool,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
            "stream": stream,
        }
        if tools:
            kwargs["tools"] = tools
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        kwargs.update(self.kwargs)
        return kwargs

    def _parse_response(self, response: Any) -> LLMResponse:
        choice = response.choices[0]
        msg = choice.message

        tool_calls: list[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {"_raw": tc.function.arguments}
                tool_calls.append(
                    ToolCall(id=tc.id, name=tc.function.name, arguments=args)
                )

        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return LLMResponse(
            content=msg.content or "",
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
        )

    async def close(self) -> None:
        await self.client.close()
