# tests/integration/test_anthropic_provider.py

"""
AnthropicClaudeProvider 测试。

覆盖:
- 构造函数: api_key 传入、环境变量读取、缺少 key 时 ValueError
- base_url 参数传递
- 真实 API 调用（仅当 ANTHROPIC_API_KEY 环境变量存在时运行）
- Mock 模式不受影响
"""
import os
import unittest
import unittest.mock

import pytest

from tools.llm import create_llm_provider, MockLLMProvider
from tools.llm.anthropic import AnthropicClaudeProvider


# ─── 构造函数测试 ──────────────────────────────────────────


class TestAnthropicProviderInit:
    """AnthropicClaudeProvider 构造函数"""

    def test_init_with_api_key(self):
        """直接传入 api_key 应成功"""
        provider = AnthropicClaudeProvider(api_key="sk-ant-test-key-123")
        assert provider.get_name() == "anthropic/claude-sonnet-4-5"

    def test_init_with_env_var(self):
        """从环境变量读取 API key"""
        with unittest.mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-env-key"}):
            provider = AnthropicClaudeProvider()
            assert provider.get_name() == "anthropic/claude-sonnet-4-5"

    def test_init_without_api_key_raises(self):
        """无 api_key 时应抛出 ValueError"""
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            # 确保环境变量中没有 key
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with pytest.raises(ValueError, match="Anthropic API key required"):
                AnthropicClaudeProvider()

    def test_init_with_custom_model(self):
        """自定义 model 参数"""
        provider = AnthropicClaudeProvider(api_key="sk-ant-xxx", model="claude-opus-4-8")
        assert provider.get_name() == "anthropic/claude-opus-4-8"

    def test_init_with_base_url(self):
        """base_url 参数应被接受且不报错"""
        provider = AnthropicClaudeProvider(
            api_key="sk-ant-xxx",
            base_url="https://my-proxy.example.com",
        )
        assert provider.get_name() == "anthropic/claude-sonnet-4-5"

    def test_init_with_base_url_none(self):
        """base_url=None 时应使用默认值"""
        provider = AnthropicClaudeProvider(api_key="sk-ant-xxx", base_url=None)
        assert provider.get_name() == "anthropic/claude-sonnet-4-5"


# ─── base_url 参数传递测试 ────────────────────────────────


class TestBaseURLParameter:
    """验证 base_url 从 create_llm_provider 正确传递"""

    def test_create_provider_with_base_url(self):
        """create_llm_provider 传递 base_url 不报错"""
        provider = create_llm_provider(
            backend="anthropic",
            api_key="sk-ant-test",
            base_url="https://proxy.example.com",
        )
        assert isinstance(provider, AnthropicClaudeProvider)

    def test_create_provider_without_base_url(self):
        """create_llm_provider 不传 base_url 也应正常"""
        provider = create_llm_provider(
            backend="anthropic",
            api_key="sk-ant-test",
        )
        assert isinstance(provider, AnthropicClaudeProvider)


# ─── Mock 不受影响测试 ────────────────────────────────────


class TestMockFallback:
    """Mock 模式不受 anthropic 变更影响"""

    def test_mock_provider_works(self):
        provider = create_llm_provider(backend="mock")
        assert isinstance(provider, MockLLMProvider)

    def test_mock_complete(self):
        provider = create_llm_provider(backend="mock")
        response = provider.complete("分析 auth 模块需求", output_format="text")
        assert response.success is True
        assert len(response.content) > 0

    def test_mock_json_output(self):
        provider = create_llm_provider(backend="mock")
        response = provider.complete("分析 auth 模块", output_format="json")
        assert response.success is True
        assert isinstance(response.parsed, dict)


# ─── 真实 API 测试（需要 ANTHROPIC_API_KEY）────────────────


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
class TestAnthropicProviderComplete:
    """真实 Claude API 调用测试（需要有效的 API key）"""

    def test_simple_text_completion(self):
        """简单文本生成"""
        provider = AnthropicClaudeProvider()
        response = provider.complete(
            "Say hello in one word.",
            max_tokens=10,
            temperature=0,
        )
        assert response.success is True
        assert len(response.content) > 0
        assert response.tokens_used > 0

    def test_json_output(self):
        """JSON 格式输出"""
        provider = AnthropicClaudeProvider()
        response = provider.complete(
            'Return a JSON object with a single field "greeting" containing "hello".',
            output_format="json",
            max_tokens=50,
        )
        assert response.success is True
        assert isinstance(response.parsed, dict)
        assert "greeting" in response.parsed

    def test_with_system_prompt(self):
        """带 system prompt 的调用"""
        provider = AnthropicClaudeProvider()
        response = provider.complete(
            "What is 2+2?",
            system_prompt="You are a math teacher. Answer concisely.",
            max_tokens=20,
        )
        assert response.success is True
        assert "4" in response.content

    def test_custom_model(self):
        """使用自定义 model"""
        provider = AnthropicClaudeProvider(model="claude-haiku-4-5-20251001")
        response = provider.complete(
            "Say hi.",
            max_tokens=10,
        )
        assert response.success is True
