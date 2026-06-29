# tools/llm/providers.py

"""
Multi-Model LLM Providers

Supports OpenAI-compatible APIs (OpenAI, Tongyi, DeepSeek, ZhipuAI, Moonshot,
Kimi, MiniMax) and Google Gemini via their respective SDKs.

Usage:
    # OpenAI-compatible
    provider = OpenAICompatibleProvider(api_key="sk-...", model="gpt-4o")
    provider = OpenAICompatibleProvider()  # reads OPENAI_API_KEY

    # Gemini
    provider = GeminiProvider(api_key="AIza...")
    provider = GeminiProvider()  # reads GEMINI_API_KEY

    # Call
    response = provider.complete("Analyze this requirement...", output_format="json")
"""

import json
import logging
import os
import re
import time
from typing import Optional

from tools.llm.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

# Retry configuration (matches AnthropicClaudeProvider pattern)
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 524, 529}
_MAX_RETRIES = 3
_BASE_DELAY_SECONDS = 2.0

# ---------------------------------------------------------------------------
# Default model mapping per vendor
# ---------------------------------------------------------------------------
_OPENAI_COMPATIBLE_DEFAULTS = {
    "openai": "gpt-4o",
    "tongyi": "qwen-turbo",
    "deepseek": "deepseek-chat",
    "zhipu": "glm-4-flash",
    "moonshot": "moonshot-v1-auto",
    "kimi": "moonshot-v1-auto",   # Kimi uses Moonshot API
    "minimax": "abab6.5-chat",
}

_GEMINI_DEFAULT_MODEL = "gemini-2.0-flash"


def _clean_json(text: str) -> str:
    """Strip markdown fences and whitespace from JSON text."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    return text


def _should_retry(exception: Exception) -> bool:
    """Check if an exception is retryable."""
    status_code = getattr(getattr(exception, "response", None), "status_code", None)
    if status_code in _RETRYABLE_STATUS_CODES:
        return True
    # Certain OpenAI SDK errors expose .status_code directly
    if hasattr(exception, "status_code") and exception.status_code in _RETRYABLE_STATUS_CODES:
        return True
    return False


# ---------------------------------------------------------------------------
# OpenAI-compatible provider
# ---------------------------------------------------------------------------

class OpenAICompatibleProvider(LLMProvider):
    """
    Provider for any OpenAI-compatible API.

    Supports: OpenAI, Tongyi (Qwen), DeepSeek, ZhipuAI, Moonshot, Kimi, MiniMax.

    Usage:
        # Standard OpenAI
        provider = OpenAICompatibleProvider(api_key="sk-...", model="gpt-4o")

        # tongyi / Qwen via OpenAI-compatible endpoint
        provider = OpenAICompatibleProvider(
            api_key="sk-...",
            model="qwen-turbo",
            base_url="https://dashscope.aliyuncs.com/v1",
        )

        # DeepSeek
        provider = OpenAICompatibleProvider(
            api_key="sk-...",
            model="deepseek-chat",
            base_url="https://api.deepseek.com/v1",
        )

        # Auto-detect from env if model not specified
        provider = OpenAICompatibleProvider(backend="openai")
    """

    def __init__(
        self,
        api_key: str = None,
        model: str = None,
        base_url: str = None,
        backend: str = "openai",
        max_tokens: int = 4096,
        timeout: float = None,
    ):
        # Resolve API key
        api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "API key required for OpenAI-compatible provider. "
                "Set OPENAI_API_KEY or pass api_key parameter."
            )

        # Resolve backend & model
        backend = backend.lower()
        if model is None:
            # Try environment variable first, then default mapping
            model = os.environ.get("OPENAI_MODEL") or _OPENAI_COMPATIBLE_DEFAULTS.get(backend)
            if model is None:
                model = "gpt-4o"

        # Resolve base_url from env if not provided
        base_url = base_url or os.environ.get("OPENAI_BASE_URL")

        # Import OpenAI SDK
        try:
            import openai
            client_kwargs = {"api_key": api_key}
            if base_url:
                client_kwargs["base_url"] = base_url
            if timeout is not None:
                client_kwargs["timeout"] = timeout
            self._client = openai.OpenAI(**client_kwargs)
        except ImportError:
            raise ImportError(
                "openai package not installed. "
                "Run: pip install openai"
            )

        self._model = model
        self._default_max_tokens = max_tokens
        self._backend = backend

    def complete(
        self,
        prompt: str,
        system_prompt: str = "",
        output_format: str = "text",
        max_tokens: int = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Call OpenAI-compatible API with retry logic."""
        max_tokens = max_tokens or self._default_max_tokens

        # Build messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Inject JSON instruction for json output_format
        json_instruction = ""
        if output_format == "json":
            json_instruction = "\n\nYou must respond with valid JSON only. No markdown fences, no explanation."
            if messages:
                messages[-1]["content"] += json_instruction

        kwargs = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }

        last_error = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = self._client.chat.completions.create(**kwargs)
                message = response.choices[0].message
                content = message.content or ""

                # Parse JSON
                parsed = None
                if output_format == "json":
                    try:
                        clean = _clean_json(content)
                        parsed = json.loads(clean)
                    except json.JSONDecodeError as e:
                        return LLMResponse(
                            content=content,
                            success=False,
                            error=f"JSON parse error: {e}",
                            model=self._model,
                        )

                tokens_used = 0
                if response.usage:
                    tokens_used = (
                        getattr(response.usage, "prompt_tokens", 0)
                        + getattr(response.usage, "completion_tokens", 0)
                    )

                return LLMResponse(
                    content=content,
                    parsed=parsed,
                    tokens_used=tokens_used,
                    model=self._model,
                    success=True,
                )

            except Exception as e:
                last_error = e
                if _should_retry(e) and attempt < _MAX_RETRIES:
                    delay = _BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                    logger.warning(
                        "[OpenAICompatibleProvider] Retryable error (status=%s, attempt=%d/%d), "
                        "retrying in %.1fs: %s",
                        getattr(e, "status_code", None),
                        attempt,
                        _MAX_RETRIES,
                        delay,
                        e,
                    )
                    time.sleep(delay)
                    continue
                break

        return LLMResponse(
            content="",
            success=False,
            error=str(last_error),
            model=self._model,
        )

    def get_name(self) -> str:
        return f"{self._backend}/{self._model}"

    async def acomplete(
        self,
        prompt: str,
        system_prompt: str = "",
        output_format: str = "text",
        max_tokens: int = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """异步调用（在线程池中执行同步 API 调用）"""
        import asyncio
        return await asyncio.to_thread(
            self.complete, prompt, system_prompt, output_format, max_tokens, temperature
        )


# ---------------------------------------------------------------------------
# Google Gemini provider
# ---------------------------------------------------------------------------

class GeminiProvider(LLMProvider):
    """
    Google Gemini LLM Provider.

    Usage:
        provider = GeminiProvider(api_key="AIza...")
        provider = GeminiProvider()  # reads GEMINI_API_KEY

        response = provider.complete("Analyze requirement...", output_format="json")
    """

    def __init__(
        self,
        api_key: str = None,
        model: str = None,
        max_tokens: int = 4096,
        timeout: float = None,
    ):
        # Resolve API key
        api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError(
                "Gemini API key required. "
                "Set GEMINI_API_KEY or pass api_key parameter."
            )

        # Resolve model
        model = model or os.environ.get("GEMINI_MODEL") or _GEMINI_DEFAULT_MODEL

        # Import google-generativeai SDK
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            self._genai_sdk = genai
        except ImportError:
            raise ImportError(
                "google-generativeai package not installed. "
                "Run: pip install google-generativeai"
            )

        self._model = model
        self._default_max_tokens = max_tokens
        self._timeout = timeout

    def complete(
        self,
        prompt: str,
        system_prompt: str = "",
        output_format: str = "text",
        max_tokens: int = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Call Gemini API with retry logic."""
        max_tokens = max_tokens or self._default_max_tokens

        # Build generation config
        generation_config = self._genai_sdk.types.GenerationConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
        )

        # Build system instruction
        system_instruction = None
        full_prompt = prompt
        if output_format == "json":
            json_suffix = (
                "\n\nYou must respond with valid JSON only. "
                "No markdown fences, no explanation."
            )
            full_prompt += json_suffix

        if system_prompt:
            system_instruction = system_prompt

        # Build model kwargs
        model_kwargs = {
            "model_name": self._model,
            "generation_config": generation_config,
        }
        if system_instruction:
            model_kwargs["system_instruction"] = system_instruction

        model = self._genai_sdk.GenerativeModel(**model_kwargs)

        kwargs = {"contents": full_prompt}
        if self._timeout is not None:
            kwargs["timeout"] = self._timeout

        last_error = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = model.generate_content(**kwargs)
                content = response.text or ""

                # Parse JSON
                parsed = None
                if output_format == "json":
                    try:
                        clean = _clean_json(content)
                        parsed = json.loads(clean)
                    except json.JSONDecodeError as e:
                        return LLMResponse(
                            content=content,
                            success=False,
                            error=f"JSON parse error: {e}",
                            model=self._model,
                        )

                tokens_used = 0
                if hasattr(response, "usage_metadata"):
                    meta = response.usage_metadata
                    tokens_used = (
                        getattr(meta, "prompt_token_count", 0)
                        + getattr(meta, "candidates_token_count", 0)
                    )

                return LLMResponse(
                    content=content,
                    parsed=parsed,
                    tokens_used=tokens_used,
                    model=self._model,
                    success=True,
                )

            except Exception as e:
                last_error = e
                if _should_retry(e) and attempt < _MAX_RETRIES:
                    delay = _BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                    logger.warning(
                        "[GeminiProvider] Retryable error (attempt=%d/%d), "
                        "retrying in %.1fs: %s",
                        attempt,
                        _MAX_RETRIES,
                        delay,
                        e,
                    )
                    time.sleep(delay)
                    continue
                break

        return LLMResponse(
            content="",
            success=False,
            error=str(last_error),
            model=self._model,
        )

    def get_name(self) -> str:
        return f"gemini/{self._model}"

    async def acomplete(
        self,
        prompt: str,
        system_prompt: str = "",
        output_format: str = "text",
        max_tokens: int = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """异步调用（在线程池中执行同步 API 调用）"""
        import asyncio
        return await asyncio.to_thread(
            self.complete, prompt, system_prompt, output_format, max_tokens, temperature
        )
