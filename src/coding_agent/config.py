"""使用 pydantic-settings 的配置管理。"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PermissionMode(str, Enum):
    """权限模式。"""

    ASK = "ask"  # 每次操作前询问
    AUTO = "auto"  # 自动批准 (危险)
    READONLY = "readonly"  # 只读


class SandboxType(str, Enum):
    """沙箱类型。"""

    LOCAL = "local"
    DOCKER = "docker"
    E2B = "e2b"


class Settings(BaseSettings):
    """全局配置，从环境变量 / .env 文件加载。"""

    model_config = SettingsConfigDict(
        env_prefix="CODING_AGENT_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # === LLM ===
    model: str = "openai:gpt-4o"
    base_url: str | None = None
    api_key: str | None = None

    # 兼容读取各厂商 key
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    zhipuai_api_key: str | None = Field(default=None, alias="ZHIPUAI_API_KEY")

    # === 工作目录 ===
    workdir: Path = Field(default=Path("."))

    # === 权限 ===
    permission: PermissionMode = PermissionMode.ASK

    # === 沙箱 ===
    sandbox: SandboxType = SandboxType.LOCAL
    docker_image: str = "python:3.12-slim"

    # === 上下文 ===
    max_tokens: int = 200_000
    max_history: int = 50

    # === 日志 ===
    log_level: str = "INFO"
    log_file: Path | None = None

    @field_validator("workdir")
    @classmethod
    def resolve_workdir(cls, v: Path) -> Path:
        return v.resolve()


# 全局单例
_settings: Settings | None = None


def _resolve_env_file(env_file: str | Path | None = None) -> str | Path | None:
    """解析 .env 文件路径（仅 ~/.coding-agent/.env）。"""
    if env_file is not None:
        return env_file
    home_env = Path.home() / ".coding-agent" / ".env"
    if home_env.exists():
        return home_env
    return None


def get_settings(env_file: str | Path | None = None) -> Settings:
    """获取全局配置单例。"""
    global _settings
    if _settings is None:
        resolved = _resolve_env_file(env_file)
        _settings = Settings(_env_file=resolved)  # type: ignore
    return _settings


def reset_settings() -> None:
    """重置配置（主要用于测试）。"""
    global _settings
    _settings = None
