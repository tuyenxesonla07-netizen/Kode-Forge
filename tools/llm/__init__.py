# tools/llm/__init__.py

"""
LLM Provider — 抽象层，支持多种 LLM 后端

用法:
    from tools.llm import create_llm_provider

    # 默认: Mock (无需 API key)
    provider = create_llm_provider()

    # Anthropic (需要 ANTHROPIC_API_KEY)
    provider = create_llm_provider("anthropic", api_key="sk-...")

    # 调用
    result = provider.complete("分析这个需求...", output_format="json")
"""

from tools.llm.base import LLMProvider, LLMResponse
from tools.llm.mock import MockLLMProvider

# 可选: Anthropic provider
try:
    from tools.llm.anthropic import AnthropicClaudeProvider
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False


def create_llm_provider(
    backend: str = "mock",
    api_key: str = None,
    model: str = None,
    **kwargs,
) -> LLMProvider:
    """
    工厂函数: 创建 LLM Provider

    Args:
        backend: "mock" 或 "anthropic"
        api_key: API key (anthropic 需要)
        model: 模型名 (默认 claude-sonnet-4-5)

    Returns:
        LLMProvider 实例
    """
    if backend == "mock":
        return MockLLMProvider(**kwargs)

    if backend == "anthropic":
        if not _ANTHROPIC_AVAILABLE:
            raise ImportError(
                "anthropic package not installed. "
                "Run: pip install anthropic --break-system-packages"
            )
        return AnthropicClaudeProvider(api_key=api_key, model=model, **kwargs)

    raise ValueError(f"Unknown LLM backend: {backend}")


__all__ = [
    "LLMProvider",
    "LLMResponse",
    "MockLLMProvider",
    "create_llm_provider",
]

if _ANTHROPIC_AVAILABLE:
    __all__.append("AnthropicClaudeProvider")
