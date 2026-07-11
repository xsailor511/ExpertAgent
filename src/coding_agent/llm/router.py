"""LLM Router — 根据 model 字符串路由到对应 Provider。"""

from __future__ import annotations

from coding_agent.config import Settings, get_settings
from coding_agent.llm.base import LLMProvider
from coding_agent.llm.openai_provider import OpenAIProvider
from coding_agent.utils.logging import get_logger

log = get_logger(__name__)


def create_llm(
    model: str | None = None,
    settings: Settings | None = None,
) -> LLMProvider:
    """根据 model 字符串创建 LLM Provider。

    支持的 model 格式:
        - "openai:gpt-4o"           -> OpenAI 官方
        - "anthropic:claude-3-5..."  -> Anthropic (走兼容接口或原生 SDK)
        - "zhipu:glm-4"             -> 智谱 AI
        - "litellm:gpt-4o"          -> LiteLLM 统一路由
        - "gpt-4o"                  -> 默认走 OpenAI
    """
    settings = settings or get_settings()
    model = model or settings.model

    # 解析 provider 前缀
    if ":" in model:
        provider_name, model_name = model.split(":", 1)
    else:
        provider_name, model_name = "openai", model

    log.info(f"Creating LLM provider: {provider_name} / {model_name}")

    if provider_name == "openai":
        return OpenAIProvider(
            model=model_name,
            api_key=settings.openai_api_key or settings.api_key,
            base_url=settings.base_url,
        )
    elif provider_name == "zhipu":
        # 智谱 GLM 兼容 OpenAI 协议
        return OpenAIProvider(
            model=model_name,
            api_key=settings.zhipuai_api_key or settings.api_key,
            base_url=settings.base_url or "https://open.bigmodel.cn/api/paas/v4",
        )
    elif provider_name == "anthropic":
        try:
            from coding_agent.llm.anthropic_provider import AnthropicProvider

            return AnthropicProvider(
                model=model_name,
                api_key=settings.anthropic_api_key or settings.api_key,
                base_url=settings.base_url,
            )
        except ImportError:
            log.warning("anthropic SDK not installed, falling back to OpenAI provider")
            return OpenAIProvider(
                model=model_name,
                api_key=settings.anthropic_api_key or settings.api_key,
                base_url=settings.base_url,
            )
    elif provider_name == "litellm":
        try:
            from coding_agent.llm.litellm_provider import LiteLLMProvider

            return LiteLLMProvider(model=model_name, api_key=settings.api_key)
        except ImportError:
            log.warning("litellm not installed, falling back to OpenAI provider")
            return OpenAIProvider(model=model_name, api_key=settings.api_key)
    else:
        log.warning(f"Unknown provider: {provider_name}, using OpenAI")
        return OpenAIProvider(
            model=model_name,
            api_key=settings.openai_api_key or settings.api_key,
            base_url=settings.base_url,
        )
