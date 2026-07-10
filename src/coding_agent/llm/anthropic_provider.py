"""Native Anthropic SDK LLM Provider — uses anthropic Python SDK directly."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from coding_agent.llm.base import (
    LLMProvider,
    LLMResponse,
    Message,
    StreamChunk,
    ToolCall,
)
from coding_agent.utils.logging import get_logger

log = get_logger(__name__)

try:
    from anthropic import AsyncAnthropic

    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


class AnthropicProvider(LLMProvider):
    """Native Anthropic SDK provider with proper tool_use content blocks.

    Supports:
    - Multi-turn chat with tool_use/tool_result content blocks
    - Streaming with content_block_delta and content_block_stop events
    - Max_tokens, temperature controls
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        if not HAS_ANTHROPIC:
            raise ImportError(
                "anthropic SDK is not installed. Install with: pip install anthropic"
            )
        super().__init__(model, api_key, base_url, **kwargs)
        client_kwargs: dict[str, Any] = {}
        if api_key:
            client_kwargs["api_key"] = api_key
        if base_url:
            client_kwargs["base_url"] = base_url
        self.client = AsyncAnthropic(**client_kwargs)

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        kwargs = self._build_kwargs(messages, tools, temperature, max_tokens)
        response = await self.client.messages.create(**kwargs)
        return self._parse_response(response)

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamChunk]:
        kwargs = self._build_kwargs(messages, tools, temperature, max_tokens)
        kwargs["stream"] = True

        tool_uses: dict[str, dict[str, Any]] = {}

        async with self.client.messages.stream(**kwargs) as stream:
            async for event in stream:
                if event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        yield StreamChunk(content=event.delta.text or "")
                    elif event.delta.type == "input_json_delta":
                        idx = str(event.index)
                        if idx not in tool_uses:
                            tool_uses[idx] = {"id": "", "name": "", "input": ""}
                        tool_uses[idx]["input"] += event.delta.partial_json or ""

                elif event.type == "content_block_start":
                    if event.content_block.type == "tool_use":
                        idx = str(event.index)
                        tool_uses[idx] = {
                            "id": event.content_block.id,
                            "name": event.content_block.name,
                            "input": "",
                        }

                elif event.type == "message_delta":
                    if event.delta.stop_reason:
                        for acc in tool_uses.values():
                            try:
                                args = json.loads(acc["input"]) if acc["input"] else {}
                            except json.JSONDecodeError:
                                args = {"_raw": acc["input"]}
                            yield StreamChunk(
                                tool_call=ToolCall(
                                    id=acc["id"],
                                    name=acc["name"],
                                    arguments=args,
                                ),
                                finish_reason=event.delta.stop_reason,
                            )
                        if not tool_uses:
                            yield StreamChunk(
                                finish_reason=event.delta.stop_reason,
                            )

                elif event.type == "message_stop":
                    break

    def _build_kwargs(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": self._convert_messages(messages),
            "temperature": temperature,
        }

        kwargs["max_tokens"] = max_tokens or 4096

        if self._system:
            kwargs["system"] = self._system

        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        return kwargs

    def _convert_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert internal Message format to Anthropic API format."""
        result: list[dict[str, Any]] = []

        system_parts = []
        for msg in messages:
            if msg.role == "system":
                system_parts.append(msg.content)
        self._system = "\n".join(system_parts) if system_parts else None

        for msg in messages:
            if msg.role == "system":
                continue

            converted: dict[str, Any] = {"role": msg.role}

            if msg.role == "user":
                converted["content"] = msg.content or ""
            elif msg.role == "assistant":
                if msg.tool_calls:
                    content: list[dict[str, Any]] = []
                    if msg.content:
                        content.append({"type": "text", "text": msg.content})
                    for tc in msg.tool_calls:
                        if isinstance(tc, dict):
                            fn = tc.get("function", {})
                            fn_name = fn.get("name", "") if isinstance(fn, dict) else ""
                            fn_args = fn.get("arguments", "{}") if isinstance(fn, dict) else "{}"
                            tc_id = tc.get("id", "")

                            if isinstance(fn_args, str):
                                try:
                                    args_dict = json.loads(fn_args)
                                except json.JSONDecodeError:
                                    args_dict = {"_raw": fn_args}
                            else:
                                args_dict = fn_args

                            content.append({
                                "type": "tool_use",
                                "id": tc_id,
                                "name": fn_name,
                                "input": args_dict,
                            })
                        elif hasattr(tc, "id"):
                            content.append({
                                "type": "tool_use",
                                "id": tc.id,
                                "name": tc.name,
                                "input": tc.arguments,
                            })
                    converted["content"] = content
                else:
                    converted["content"] = msg.content or ""
            elif msg.role == "tool":
                converted["role"] = "user"
                converted["content"] = [
                    {
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id or "",
                        "content": msg.content or "",
                    }
                ]

            result.append(converted)

        return result

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert OpenAI-style tool schemas to Anthropic tool format."""
        anthropic_tools = []
        for tool in tools:
            fn = tool.get("function", tool) if isinstance(tool, dict) else tool
            anthropic_tools.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            })
        return anthropic_tools

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse an Anthropic Message response into LLMResponse."""
        content_str = ""
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                content_str = block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else {},
                    )
                )

        usage = {}
        if hasattr(response, "usage"):
            usage = {}
            if hasattr(response.usage, "input_tokens"):
                usage["prompt_tokens"] = response.usage.input_tokens
            if hasattr(response.usage, "output_tokens"):
                usage["completion_tokens"] = response.usage.output_tokens

        return LLMResponse(
            content=content_str,
            tool_calls=tool_calls,
            finish_reason=response.stop_reason or "stop",
            usage=usage,
        )

    async def close(self) -> None:
        await self.client.close()
