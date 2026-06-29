# tools/llm/model_switcher.py
"""
LLM Model Switcher — unified provider registry, runtime switching, and connectivity testing.

Provides:
  1. ProviderConfig — dataclass for provider configuration
  2. ModelRegistry — built-in registry of 20+ LLM providers
  3. ModelSwitcher — runtime model switching with fallback and connectivity testing

Usage:
    from tools.llm.model_switcher import ModelSwitcher, ModelRegistry, ProviderConfig

    registry = ModelRegistry()
    switcher = ModelSwitcher(registry)
    switcher.switch("openai", "gpt-4o")
    switcher.test_all()
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------

@dataclass
class ProviderConfig:
    """LLM provider configuration."""
    name: str
    display_name: str
    default_model: str
    api_key_env: str
    base_url_env: str = ""
    models: list[str] = field(default_factory=list)
    supports_json: bool = True
    supports_streaming: bool = True
    notes: str = ""


# ---------------------------------------------------------------------------
# Built-in provider registry (20+ providers)
# ---------------------------------------------------------------------------

DEFAULT_PROVIDERS: dict[str, ProviderConfig] = {
    # --- Anthropic ---
    "anthropic": ProviderConfig(
        name="anthropic",
        display_name="Anthropic (Claude)",
        default_model="claude-sonnet-4-6",
        api_key_env="ANTHROPIC_API_KEY",
        base_url_env="ANTHROPIC_BASE_URL",
        models=["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
        notes="Direct or via gateway",
    ),
    # --- OpenAI ---
    "openai": ProviderConfig(
        name="openai",
        display_name="OpenAI (GPT)",
        default_model="gpt-4o",
        api_key_env="OPENAI_API_KEY",
        base_url_env="OPENAI_BASE_URL",
        models=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1", "o1-mini"],
    ),
    # --- Google ---
    "gemini": ProviderConfig(
        name="gemini",
        display_name="Google (Gemini)",
        default_model="gemini-2.0-flash",
        api_key_env="GEMINI_API_KEY",
        models=["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-2.0-pro"],
    ),
    # --- Tongyi (Qwen) ---
    "tongyi": ProviderConfig(
        name="tongyi",
        display_name="Alibaba (Tongyi/Qwen)",
        default_model="qwen-turbo",
        api_key_env="OPENAI_API_KEY",
        base_url_env="OPENAI_BASE_URL",
        models=["qwen-turbo", "qwen-plus", "qwen-max"],
        notes="Requires OpenAI SDK + compatible endpoint",
    ),
    # --- DeepSeek ---
    "deepseek": ProviderConfig(
        name="deepseek",
        display_name="DeepSeek",
        default_model="deepseek-chat",
        api_key_env="OPENAI_API_KEY",
        base_url_env="OPENAI_BASE_URL",
        models=["deepseek-chat", "deepseek-reasoner"],
    ),
    # --- ZhipuAI (GLM) ---
    "zhipu": ProviderConfig(
        name="zhipu",
        display_name="ZhipuAI (GLM)",
        default_model="glm-4-flash",
        api_key_env="OPENAI_API_KEY",
        base_url_env="OPENAI_BASE_URL",
        models=["glm-4-flash", "glm-4", "glm-4-air"],
    ),
    # --- Moonshot (Kimi) ---
    "moonshot": ProviderConfig(
        name="moonshot",
        display_name="Moonshot (Kimi)",
        default_model="moonshot-v1-auto",
        api_key_env="OPENAI_API_KEY",
        base_url_env="OPENAI_BASE_URL",
        models=["moonshot-v1-auto", "moonshot-v1-8k", "moonshot-v1-32k"],
    ),
    # --- MiniMax ---
    "minimax": ProviderConfig(
        name="minimax",
        display_name="MiniMax",
        default_model="abab6.5-chat",
        api_key_env="OPENAI_API_KEY",
        base_url_env="OPENAI_BASE_URL",
        models=["abab6.5-chat", "abab6.5s-chat", "abab5.5-chat"],
    ),
    # --- Doubao (ByteDance) ---
    "doubao": ProviderConfig(
        name="doubao",
        display_name="ByteDance (Doubao)",
        default_model="doubao-pro-32k",
        api_key_env="OPENAI_API_KEY",
        base_url_env="OPENAI_BASE_URL",
        models=["doubao-pro-32k", "doubao-pro-4k", "doubao-lite"],
        notes="Volcengine",
    ),
    # --- Wenxin (Baidu ERNIE) ---
    "wenxin": ProviderConfig(
        name="wenxin",
        display_name="Baidu (Wenxin/ERNIE)",
        default_model="ernie-4.0",
        api_key_env="OPENAI_API_KEY",
        base_url_env="OPENAI_BASE_URL",
        models=["ernie-4.0", "ernie-3.5", "ernie-speed"],
    ),
    # --- Mock (for testing) ---
    "mock": ProviderConfig(
        name="mock",
        display_name="Mock (Testing)",
        default_model="mock-default",
        api_key_env="",
        models=["mock-default"],
        notes="For testing, no API key needed",
    ),
}


# ---------------------------------------------------------------------------
# Model Registry
# ---------------------------------------------------------------------------

class ModelRegistry:
    """LLM provider registry with built-in 20+ providers."""

    def __init__(self, extra_providers: dict[str, ProviderConfig] | None = None) -> None:
        self._providers: dict[str, ProviderConfig] = dict(DEFAULT_PROVIDERS)
        if extra_providers:
            self._providers.update(extra_providers)

    def get(self, name: str) -> Optional[ProviderConfig]:
        """Get provider configuration."""
        return self._providers.get(name.lower())

    def list_providers(self) -> list[str]:
        """List all provider names."""
        return list(self._providers.keys())

    def list_display(self) -> list[dict[str, Any]]:
        """List all providers with display info."""
        result = []
        for name, cfg in self._providers.items():
            has_key = bool(os.environ.get(cfg.api_key_env))
            result.append({
                "name": name,
                "display_name": cfg.display_name,
                "default_model": cfg.default_model,
                "has_api_key": has_key,
                "models": cfg.models,
                "notes": cfg.notes,
            })
        return result

    def add_provider(self, config: ProviderConfig) -> None:
        """Dynamically add a provider."""
        self._providers[config.name.lower()] = config

    def remove_provider(self, name: str) -> bool:
        """Remove a provider."""
        key = name.lower()
        if key in self._providers:
            del self._providers[key]
            return True
        return False

    def get_api_key(self, provider_name: str) -> str | None:
        """Get API key for a provider."""
        cfg = self.get(provider_name)
        if not cfg:
            return None
        return os.environ.get(cfg.api_key_env)

    def get_base_url(self, provider_name: str) -> str | None:
        """Get base URL for a provider."""
        cfg = self.get(provider_name)
        if not cfg or not cfg.base_url_env:
            return None
        return os.environ.get(cfg.base_url_env)

    def to_json(self) -> str:
        """Serialize to JSON."""
        data = {
            name: {
                "display_name": cfg.display_name,
                "default_model": cfg.default_model,
                "models": cfg.models,
                "has_api_key": bool(os.environ.get(cfg.api_key_env)),
            }
            for name, cfg in self._providers.items()
        }
        return json.dumps(data, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Model Switcher
# ---------------------------------------------------------------------------

class ModelSwitcher:
    """Runtime LLM model switcher.

    Supports:
      - Switch to specific provider + model
      - Auto-select best available model
      - Fallback chain (primary fails → fallback)
      - Connectivity testing
    """

    def __init__(self, registry: ModelRegistry | None = None) -> None:
        self.registry = registry or ModelRegistry()
        self._current_provider: str = "mock"
        self._current_model: str = "mock"
        self._fallback_chain: list[tuple[str, str]] = []

    @property
    def current(self) -> tuple[str, str]:
        """Return current (provider, model)."""
        return self._current_provider, self._current_model

    def switch(self, provider: str, model: str | None = None) -> bool:
        """Switch to a specific provider.

        Args:
            provider: Provider name.
            model: Model name (None = use provider default).

        Returns:
            Whether the switch succeeded.
        """
        cfg = self.registry.get(provider)
        if not cfg:
            logger.error("Unknown provider: %s", provider)
            return False

        resolved_model = model or cfg.default_model
        if resolved_model not in cfg.models and model is not None:
            logger.warning(
                "Model %s not in known list for %s, attempting anyway",
                resolved_model, provider,
            )

        self._current_provider = provider
        self._current_model = resolved_model
        logger.info("Switched to %s/%s", provider, resolved_model)
        return True

    def auto_select(self) -> tuple[str, str]:
        """Auto-select the best available model.

        Priority:
          1. Provider with existing API key
          2. Anthropic > OpenAI > Gemini > others
          3. Mock (last resort)

        Returns:
            (provider, model) tuple.
        """
        priority_order = ["anthropic", "openai", "gemini", "tongyi", "deepseek", "zhipu"]

        for provider in priority_order:
            cfg = self.registry.get(provider)
            if cfg and self.registry.get_api_key(provider):
                self._current_provider = provider
                self._current_model = cfg.default_model
                logger.info("Auto-selected: %s/%s", provider, cfg.default_model)
                return provider, cfg.default_model

        self._current_provider = "mock"
        self._current_model = "mock"
        logger.info("Auto-selected: mock (no API keys found)")
        return "mock", "mock"

    def set_fallback_chain(self, chain: list[tuple[str, str]]) -> None:
        """Set the fallback chain.

        Args:
            chain: [(provider, model), ...] ordered by priority.
        """
        self._fallback_chain = chain

    def create_provider(self, **kwargs: Any):
        """Create an LLM provider instance based on current configuration.

        Auto-reads create_llm_provider.

        Returns:
            LLMProvider instance.
        """
        from tools.llm import create_llm_provider

        provider = self._current_provider
        model = self._current_model

        if provider == "mock":
            return create_llm_provider("mock")

        # Anthropic: support base_url
        if provider == "anthropic":
            base_url = self.registry.get_base_url("anthropic")
            return create_llm_provider("anthropic", model=model, base_url=base_url or None)

        # OpenAI-compatible
        return create_llm_provider(provider, model=model)

    def test_provider(self, provider: str, model: str | None = None) -> dict[str, Any]:
        """Test connectivity for a single provider.

        Returns:
            Test result dict.
        """
        cfg = self.registry.get(provider)
        if not cfg:
            return {"provider": provider, "status": "error", "error": "Unknown provider"}

        resolved_model = model or cfg.default_model
        has_key = bool(self.registry.get_api_key(provider))

        if not has_key:
            return {
                "provider": provider,
                "model": resolved_model,
                "status": "no_api_key",
                "env_var": cfg.api_key_env,
            }

        # Try actual API call
        start = time.time()
        try:
            from tools.llm import create_llm_provider

            if provider == "anthropic":
                base_url = self.registry.get_base_url("anthropic")
                p = create_llm_provider("anthropic", model=resolved_model, base_url=base_url or None)
            else:
                p = create_llm_provider(provider, model=resolved_model)

            response = p.complete("Hello", max_tokens=10)
            elapsed = (time.time() - start) * 1000

            return {
                "provider": provider,
                "model": resolved_model,
                "status": "ok" if response.success else "error",
                "latency_ms": round(elapsed, 1),
                "tokens": response.tokens_used,
                "error": response.error,
            }
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            return {
                "provider": provider,
                "model": resolved_model,
                "status": "error",
                "latency_ms": round(elapsed, 1),
                "error": str(e),
            }

    def test_all(self) -> list[dict[str, Any]]:
        """Test all providers with API keys."""
        results = []
        for name in self.registry.list_providers():
            if self.registry.get_api_key(name):
                result = self.test_provider(name)
                results.append(result)
                logger.info(
                    "Test %s: %s (%.0fms)",
                    name,
                    result["status"],
                    result.get("latency_ms", 0),
                )
        return results

    def status_display(self) -> dict[str, Any]:
        """Return current status summary."""
        return {
            "current_provider": self._current_provider,
            "current_model": self._current_model,
            "available_providers": self.registry.list_providers(),
            "has_api_key": {
                name: bool(self.registry.get_api_key(name))
                for name in self.registry.list_providers()
            },
            "fallback_chain": self._fallback_chain,
        }

    def __repr__(self) -> str:
        return f"ModelSwitcher(current={self._current_provider}/{self._current_model})"
