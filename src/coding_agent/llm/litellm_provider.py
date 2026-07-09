"""LiteLLM Provider (可选，统一接入 100+ LLM)。"""

from __future__ import annotations

from typing import Any, AsyncIterator, Optional

from coding_agent.llm.base import LLMProvider, LLMResponse, Message, StreamChunk, ToolCall
from coding_agent.utils.logging import get_logger

log = get_logger(__name__)


class LiteLLMProvider(LLMProvider):
    """基于 litellm 的统一 Provider。"""

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(model, api_key, **kwargs)
        import litellm

        litellm.set_verbose = False
        self._litellm = litellm

    async def chat(
        self,
        messages: list[Message],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        kwargs = self._build_kwargs(messages, tools, temperature, max_tokens)
        response = await self._litellm.acompletion(**kwargs)
        return self._parse(response)

    async def stream(
        self,
        messages: list[Message],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[StreamChunk]:
        kwargs = self._build_kwargs(messages, tools, temperature, max_tokens)
        kwargs["stream"] = True
        response = await self._litellm.acompletion(**kwargs)
        async for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None) or ""
            if content:
                yield StreamChunk(content=content)
            if chunk.choices[0].finish_reason:
                yield StreamChunk(finish_reason=chunk.choices[0].finish_reason)

    def _build_kwargs(
        self,
        messages: list[Message],
        tools: Optional[list[dict[str, Any]]],
        temperature: float,
        max_tokens: Optional[int],
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if self.api_key:
            kwargs["api_key"] = self.api_key
        kwargs.update(self.kwargs)
        return kwargs

    def _parse(self, response: Any) -> LLMResponse:
        choice = response.choices[0]
        msg = choice.message
        tool_calls: list[ToolCall] = []
        if getattr(msg, "tool_calls", None):
            import json

            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except (json.JSONDecodeError, AttributeError):
                    args = {}
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        return LLMResponse(
            content=msg.content or "",
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
        )
