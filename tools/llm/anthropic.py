# tools/llm/anthropic.py

"""
Anthropic Claude LLM Provider

需要: pip install anthropic --break-system-packages
需要: 环境变量 ANTHROPIC_API_KEY 或传入 api_key
"""

import json
import os
import re

from tools.llm.base import LLMProvider, LLMResponse


class AnthropicClaudeProvider:
    """
    Anthropic Claude API Provider

    用法:
        provider = AnthropicClaudeProvider(api_key="sk-...")
        # 或
        provider = AnthropicClaudeProvider()  # 从 ANTHROPIC_API_KEY 读取

        response = provider.complete("分析需求...", output_format="json")
    """

    def __init__(
        self,
        api_key: str = None,
        model: str = "claude-sonnet-4-5",
        max_tokens: int = 4096,
    ):
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "Anthropic API key required. "
                "Set ANTHROPIC_API_KEY or pass api_key parameter."
            )

        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=api_key)
        except ImportError:
            raise ImportError(
                "anthropic package not installed. "
                "Run: pip install anthropic --break-system-packages"
            )

        self._model = model
        self._default_max_tokens = max_tokens

    def complete(
        self,
        prompt: str,
        system_prompt: str = "",
        output_format: str = "text",
        max_tokens: int = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """调用 Claude API"""
        max_tokens = max_tokens or self._default_max_tokens

        # 构建 system prompt
        system = system_prompt
        if output_format == "json":
            system = (system + "\n\n" if system else "")
            system += "You must respond with valid JSON only. No markdown fences, no explanation."

        try:
            kwargs = {
                "model": self._model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system:
                kwargs["system"] = system

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
            return LLMResponse(
                content="",
                success=False,
                error=str(e),
                model=self._model,
            )

    def get_name(self) -> str:
        return f"anthropic/{self._model}"
