# tools/llm/base.py

"""
LLM Provider 抽象基类
"""

from dataclasses import dataclass
from typing import Optional, Any
from abc import ABC, abstractmethod


@dataclass
class LLMResponse:
    """LLM 调用返回结果"""
    content: str                      # 原始文本输出
    parsed: Optional[Any] = None      # 解析后的结构化数据
    tokens_used: int = 0              # token 消耗
    model: str = ""                   # 使用的模型
    success: bool = True              # 是否成功
    error: Optional[str] = None       # 错误信息


class LLMProvider(ABC):
    """LLM Provider 抽象基类"""

    @abstractmethod
    def complete(
        self,
        prompt: str,
        system_prompt: str = "",
        output_format: str = "text",   # "text" | "json"
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        调用 LLM 生成回复

        Args:
            prompt: 用户提示
            system_prompt: 系统提示
            output_format: 输出格式
            max_tokens: 最大 token 数
            temperature: 温度

        Returns:
            LLMResponse
        """
        ...

    async def acomplete(
        self,
        prompt: str,
        system_prompt: str = "",
        output_format: str = "text",
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        异步调用 LLM 生成回复。

        默认实现调用同步 complete() 方法。
        支持异步的 Provider 应覆盖此方法。

        Args:
            prompt: 用户提示
            system_prompt: 系统提示
            output_format: 输出格式
            max_tokens: 最大 token 数
            temperature: 温度

        Returns:
            LLMResponse
        """
        return self.complete(prompt, system_prompt, output_format, max_tokens, temperature)

    @abstractmethod
    def get_name(self) -> str:
        """返回 Provider 名称"""
        ...
