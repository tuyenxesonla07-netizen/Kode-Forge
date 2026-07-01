# tools/llm/anthropic.py

"""
Anthropic Claude LLM Provider

支持两种调用模式:
  1. 直连 Anthropic API（标准 API key: sk-ant-...）
  2. 通过自定义网关/代理（非标准 key + base_url）

用法:
    # 直连模式
    provider = AnthropicClaudeProvider(api_key="sk-ant-...")

    # 网关模式（如 Claude Desktop gateway）
    provider = AnthropicClaudeProvider(
        api_key="sk-...",
        base_url="https://your-gateway.example.com",
    )

    # 从环境变量读取
    provider = AnthropicClaudeProvider()  # 读取 ANTHROPIC_API_KEY 和 ANTHROPIC_BASE_URL
"""

import json
import logging
import os
import random
import re
import time

from tools.llm.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

# 可重试的 API 错误码
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 524, 529}
_MAX_RETRIES = 3
_BASE_DELAY_SECONDS = 2.0
_DEFAULT_TIMEOUT_SECONDS = 120.0


def _mask_error(exc: Exception) -> str:
    """
    Turn an HTTP/SDK exception into a safe, non-leaking error string.

    401/403 responses from upstream gateways often contain full response bodies
    (including token fragments or internal hostnames). Strip those details so
    they never reach end-user output.
    """
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if status_code == 401:
        return "LLM provider returned 401 — check your API key / token."
    if status_code == 403:
        return "LLM provider returned 403 — key may lack permission for this model."
    return str(exc)


class AnthropicClaudeProvider(LLMProvider):
    """
    Anthropic Claude API Provider

    用法:
        provider = AnthropicClaudeProvider(api_key="sk-...")
        # 或
        provider = AnthropicClaudeProvider()  # 从 ANTHROPIC_API_KEY 读取
        # 自定义 base_url（代理/企业网关）
        provider = AnthropicClaudeProvider(api_key="sk-...", base_url="https://my-proxy.example.com")

        response = provider.complete("分析需求...", output_format="json")
    """

    def __init__(
        self,
        api_key: str = None,
        model: str = None,
        max_tokens: int = 4096,
        base_url: str = None,
    ) -> None:
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "Anthropic API key required. "
                "Set ANTHROPIC_API_KEY or pass api_key parameter."
            )

        # 自动检测模型
        if model is None:
            model = "claude-sonnet-4-5"

        # 自动检测 base_url：从环境变量读取
        base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL")

        try:
            import anthropic
            client_kwargs = {"api_key": api_key}
            if base_url:
                client_kwargs["base_url"] = base_url
            self._client = anthropic.Anthropic(**client_kwargs)
        except ImportError:
            raise ImportError(
                "anthropic package not installed. "
                "Run: pip install anthropic"
            )

        self._model = model
        self._default_max_tokens = max_tokens
        self._timeout = _DEFAULT_TIMEOUT_SECONDS

    def complete(
        self,
        prompt: str,
        system_prompt: str = "",
        output_format: str = "text",
        max_tokens: int = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """调用 Claude API（带重试）"""
        max_tokens = max_tokens or self._default_max_tokens

        # 构建 system prompt
        system = system_prompt
        if output_format == "json":
            system = (system + "\n\n" if system else "")
            system += "You must respond with valid JSON only. No markdown fences, no explanation."

        kwargs = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system

        last_error = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                message = self._client.messages.create(**kwargs)
                content = message.content[0].text if message.content else ""

                # 解析 JSON
                parsed = None
                if output_format == "json":
                    try:
                        # 清理可能的 markdown 代码块
                        clean = content.strip()
                        if clean.startswith("```"):
                            clean = re.sub(r"^```(?:json)?\s*\n?", "", clean)
                            clean = re.sub(r"\n?```\s*$", "", clean)
                        parsed = json.loads(clean)
                    except json.JSONDecodeError as e:
                        return LLMResponse(
                            content=content,
                            success=False,
                            error=f"JSON parse error: {e}",
                            model=self._model,
                        )

                return LLMResponse(
                    content=content,
                    parsed=parsed,
                    tokens_used=message.usage.input_tokens + message.usage.output_tokens,
                    model=self._model,
                    success=True,
                )

            except Exception as e:
                last_error = e
                status_code = getattr(getattr(e, 'response', None), 'status_code', None)
                if status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_RETRIES:
                    # Gap 20: 添加 jitter 防止 thundering herd
                    delay = _BASE_DELAY_SECONDS * (2 ** (attempt - 1)) + random.random()
                    logger.warning(
                        "[AnthropicClaudeProvider] Retryable error (status=%s, attempt=%d/%d), "
                        "retrying in %.1fs: %s",
                        status_code, attempt, _MAX_RETRIES, delay, e,
                    )
                    time.sleep(delay)
                    continue
                break

        return LLMResponse(
            content="",
            success=False,
            error=_mask_error(last_error),
            model=self._model,
        )

    def get_name(self) -> str:
        return f"anthropic/{self._model}"

    async def acomplete(
        self,
        prompt: str,
        system_prompt: str = "",
        output_format: str = "text",
        max_tokens: int = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """异步调用（在线程池中执行同步 API 调用，带超时）"""
        import asyncio
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self.complete, prompt, system_prompt, output_format, max_tokens, temperature
                ),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            return LLMResponse(
                content="",
                success=False,
                error=f"LLM call timed out after {self._timeout}s",
                model=self._model,
            )
