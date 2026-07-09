"""Tool 基类 — 所有工具继承此类，自动生成 JSON Schema。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Optional

from pydantic import BaseModel, Field


class ToolError(Exception):
    """工具执行错误。"""

    def __init__(self, message: str, *, recoverable: bool = True) -> None:
        super().__init__(message)
        self.recoverable = recoverable


@dataclass
class ToolResult:
    """工具执行结果。"""

    content: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        prefix = "[ERROR] " if self.is_error else ""
        return f"{prefix}{self.content}"


class Tool(ABC):
    """工具基类。

    子类需要:
        1. 定义 `name`, `description` 类属性
        2. 定义 `Params` 内部 pydantic 模型描述参数
        3. 实现 `execute()` 方法
    """

    name: ClassVar[str]
    description: ClassVar[str]
    # 是否需要用户确认 (写操作 / 危险操作设为 True)
    requires_confirmation: ClassVar[bool] = False

    class Params(BaseModel):
        """工具参数 schema，子类覆盖。"""
        pass

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """执行工具。"""
        ...

    def validate(self, arguments: dict[str, Any]) -> "Tool.Params":
        """校验参数。"""
        return self.Params.model_validate(arguments)

    def to_openai_schema(self) -> dict[str, Any]:
        """转换为 OpenAI function calling schema。"""
        schema = self.Params.model_json_schema()
        # OpenAI 要求移除 title 等字段
        schema = _clean_schema(schema)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }


def _clean_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """清理 JSON Schema，移除 pydantic 自动添加的 title 字段。"""
    if isinstance(schema, dict):
        schema.pop("title", None)
        for key, value in list(schema.items()):
            schema[key] = _clean_schema(value)
    elif isinstance(schema, list):
        return [_clean_schema(item) for item in schema]
    return schema
