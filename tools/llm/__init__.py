# tools/llm/__init__.py

"""
LLM Provider 抽象层，支持多种 LLM 后端。

用法:
    from tools.llm import create_llm_provider

    # 默认: Mock (无需 API key)
    provider = create_llm_provider()

    # Anthropic (需要 ANTHROPIC_API_KEY)
    provider = create_llm_provider("anthropic", api_key="sk-...")

    # OpenAI / Tongyi / DeepSeek / ZhipuAI / Moonshot / Kimi / MiniMax
    provider = create_llm_provider("openai", api_key="sk-...", model="gpt-4o")
    provider = create_llm_provider("tongyi", api_key="sk-...", model="qwen-turbo")
    provider = create_llm_provider("deepseek", api_key="sk-...")

    # Google Gemini
    provider = create_llm_provider("gemini", api_key="AIza...")

    # 从环境变量自动检测
    provider = create_llm_provider("openai")  # 读取 OPENAI_API_KEY
    provider = create_llm_provider("gemini")  # 读取 GEMINI_API_KEY

    # 调用
    result = provider.complete("分析这个需求..", output_format="json")
"""

from tools.llm.base import LLMProvider, LLMResponse
from tools.llm.mock import MockLLMProvider
from tools.exceptions import LLMProviderNotFoundError

import os
import logging

logger = logging.getLogger(__name__)

# ── Plugin discovery (entry_points) ──────────────────────────
_discovered_plugins: dict = {}
_plugins_loaded: bool = False


def _ensure_plugins_loaded():
    """Load discovered plugins once. Swallows exceptions for robustness."""
    global _discovered_plugins, _plugins_loaded
    if _plugins_loaded:
        return
    try:
        from tools.llm.plugin import PluginLoader
        loader = PluginLoader()
        _discovered_plugins = loader.discover()
        if _discovered_plugins:
            logger.info("[LLM] Discovered %d plugin(s): %s",
                        len(_discovered_plugins), list(_discovered_plugins.keys()))
    except Exception as e:
        logger.warning("[LLM] Plugin discovery failed (non-fatal): %s", e)
    _plugins_loaded = True

# Optional providers — gracefully handle missing packages
try:
    from tools.llm.anthropic import AnthropicClaudeProvider
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

try:
    from tools.llm.providers import OpenAICompatibleProvider, GeminiProvider
    _OPENAI_COMPATIBLE_AVAILABLE = True
    _GEMINI_AVAILABLE = True
except ImportError:
    _OPENAI_COMPATIBLE_AVAILABLE = False
    _GEMINI_AVAILABLE = False


# ---------------------------------------------------------------------------
# Backend registry for OpenAI-compatible providers
# ---------------------------------------------------------------------------
_OPENAI_COMPATIBLE_BACKENDS = {
    "openai": {"default_model": "gpt-4o", "api_key_env": "OPENAI_API_KEY", "base_url_env": "OPENAI_BASE_URL"},
    "tongyi": {"default_model": "qwen-turbo", "api_key_env": "OPENAI_API_KEY", "base_url_env": "OPENAI_BASE_URL"},
    "qwen": {"default_model": "qwen-turbo", "api_key_env": "OPENAI_API_KEY", "base_url_env": "OPENAI_BASE_URL"},
    "deepseek": {"default_model": "deepseek-chat", "api_key_env": "OPENAI_API_KEY", "base_url_env": "OPENAI_BASE_URL"},
    "zhipu": {"default_model": "glm-4-flash", "api_key_env": "OPENAI_API_KEY", "base_url_env": "OPENAI_BASE_URL"},
    "zhipuai": {"default_model": "glm-4-flash", "api_key_env": "OPENAI_API_KEY", "base_url_env": "OPENAI_BASE_URL"},
    "moonshot": {"default_model": "moonshot-v1-auto", "api_key_env": "OPENAI_API_KEY", "base_url_env": "OPENAI_BASE_URL"},
    "kimi": {"default_model": "moonshot-v1-auto", "api_key_env": "OPENAI_API_KEY", "base_url_env": "OPENAI_BASE_URL"},
    "minimax": {"default_model": "abab6.5-chat", "api_key_env": "OPENAI_API_KEY", "base_url_env": "OPENAI_BASE_URL"},
}


def _auto_detect_backend() -> str:
    """
    Auto-detect the best available LLM backend from environment variables.

    Priority:
        1. ANTHROPIC_API_KEY -> anthropic
        2. OPENAI_API_KEY -> openai (default)
        3. GEMINI_API_KEY -> gemini
        4. Mock fallback
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    return "mock"


def create_llm_provider(
    backend: str = None,
    api_key: str = None,
    model: str = None,
    base_url: str = None,
    **kwargs,
) -> LLMProvider:
    """
    Create an LLM provider instance.

    Plugin discovery runs first: if the backend matches a discovered plugin
    (via entry_points), it is loaded through the plugin system. Otherwise,
    falls back to the built-in provider registry.

    Args:
        backend: Provider backend name. One of:
            - "mock" (default, no API key needed)
            - "anthropic" (ANTHROPIC_API_KEY)
            - "openai", "tongyi", "qwen", "deepseek", "zhipu", "zhipuai",
              "moonshot", "kimi", "minimax" (OPENAI_API_KEY + openai SDK)
            - "gemini" (GEMINI_API_KEY)
            - Any name registered via cc.plugins.providers entry_points
            - None: auto-detect from environment variables
        api_key: API key (overrides environment variable)
        model: Model name (overrides default for backend)
        base_url: Custom API base URL (OpenAI-compatible only)
        **kwargs: Additional provider-specific arguments

    Returns:
        LLMProvider instance
    """
    # Auto-detect if no backend specified
    if backend is None:
        backend = _auto_detect_backend()
        logger.info("Auto-detected LLM backend: %s", backend)

    backend = backend.lower()

    # --- Plugin discovery (entry_points) ---
    _ensure_plugins_loaded()
    if backend in _discovered_plugins:
        logger.info("[LLM] Loading '%s' via plugin system", backend)
        from tools.llm.plugin import PluginLoader
        meta = _discovered_plugins[backend]
        plugin_kwargs = {"api_key": api_key, "model": model}
        if base_url:
            plugin_kwargs["base_url"] = base_url
        plugin_kwargs.update(kwargs)
        return PluginLoader().load(backend, **plugin_kwargs)

    # --- Mock ---
    if backend == "mock":
        kwargs.pop("base_url", None)
        return MockLLMProvider(**kwargs)

    # --- Anthropic ---
    if backend == "anthropic":
        if not _ANTHROPIC_AVAILABLE:
            raise ImportError(
                "anthropic package not installed. "
                "Run: pip install anthropic"
            )
        # Auto-detect base_url and model from env if not explicitly passed
        base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL")
        model = model or os.environ.get("ANTHROPIC_MODEL")
        provider_kwargs = {"api_key": api_key, "model": model}
        if base_url:
            provider_kwargs["base_url"] = base_url
        return AnthropicClaudeProvider(**provider_kwargs)

    # --- OpenAI-compatible backends ---
    if backend in _OPENAI_COMPATIBLE_BACKENDS:
        if not _OPENAI_COMPATIBLE_AVAILABLE:
            raise ImportError(
                "openai package not installed. "
                "Run: pip install openai"
            )
        config = _OPENAI_COMPATIBLE_BACKENDS[backend]
        # Resolve API key from specific env var or fallback to OPENAI_API_KEY
        resolved_api_key = api_key or os.environ.get(config["api_key_env"])
        # Resolve base_url
        resolved_base_url = base_url or os.environ.get(config["base_url_env"])
        # Resolve model: explicit param > OPENAI_MODEL env > backend default
        resolved_model = (
            model
            or os.environ.get("OPENAI_MODEL")
            or config["default_model"]
        )
        provider_kwargs = {
            "api_key": resolved_api_key,
            "model": resolved_model,
            "backend": backend,
        }
        if resolved_base_url:
            provider_kwargs["base_url"] = resolved_base_url
        return OpenAICompatibleProvider(**provider_kwargs)

    # --- Gemini ---
    if backend == "gemini":
        if not _GEMINI_AVAILABLE:
            raise ImportError(
                "google-generativeai package not installed. "
                "Run: pip install google-generativeai"
            )
        return GeminiProvider(api_key=api_key, model=model, **kwargs)

    raise LLMProviderNotFoundError(backend)


__all__ = [
    "LLMProvider",
    "LLMResponse",
    "MockLLMProvider",
    "create_llm_provider",
]

if _ANTHROPIC_AVAILABLE:
    __all__.append("AnthropicClaudeProvider")

if _OPENAI_COMPATIBLE_AVAILABLE:
    __all__.append("OpenAICompatibleProvider")

if _GEMINI_AVAILABLE:
    __all__.append("GeminiProvider")
