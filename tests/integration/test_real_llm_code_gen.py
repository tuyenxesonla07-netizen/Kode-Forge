# tests/integration/test_real_llm_code_gen.py
"""
P0-1: 真实 LLM 代码生成端到端集成测试。

覆盖:
  - ClaudeCodeExecutor: 超时控制、AST 验证重试、接口一致性检查
  - CodexSupervisor.generate_code: 真实 LLM 调用、fallback 路径
  - Mock 路径不受影响

真实 API 测试仅当 ANTHROPIC_API_KEY 环境变量存在时运行。
"""
import ast
import os
import unittest.mock

import pytest

from tools.llm import create_llm_provider
from tools.llm.mock import MockLLMProvider


# ---------------------------------------------------------------------------
# ClaudeCodeExecutor 单元测试（使用 Mock）
# ---------------------------------------------------------------------------

class TestClaudeCodeExecutorTimeout:
    """ClaudeCodeExecutor 超时控制测试"""

    def test_timeout_triggers_on_slow_provider(self):
        """Provider 超时应抛出 TimeoutError 并重试"""
        from agents.supervisor.agent_executor import ClaudeCodeExecutor

        class SlowProvider:
            def complete(self, prompt, system_prompt="", **kwargs):
                import time
                time.sleep(5)  # 模拟慢响应
                from tools.llm.base import LLMResponse
                return LLMResponse(content="print('ok')", success=True)

        executor = ClaudeCodeExecutor(llm_provider=SlowProvider())
        # 0.5s 超时，应快速返回空（不等待 5s）
        code = executor.generate_code(
            spec={"interfaces": []},
            module_name="test_module",
            timeout=0.5,
        )
        assert code == ""  # 超时返回空

    def test_successful_generation_no_retry(self):
        """正常响应不触发重试"""
        from agents.supervisor.agent_executor import ClaudeCodeExecutor

        class FastProvider:
            call_count = 0

            def complete(self, prompt, system_prompt="", **kwargs):
                FastProvider.call_count += 1
                from tools.llm.base import LLMResponse
                return LLMResponse(content="x: int = 1\n", success=True)

        provider = FastProvider()
        executor = ClaudeCodeExecutor(llm_provider=provider)
        code = executor.generate_code(
            spec={"interfaces": []},
            module_name="test_module",
            timeout=30.0,
        )
        assert code.strip() == "x: int = 1"
        assert provider.call_count == 1

    def test_ast_syntax_error_triggers_retry(self):
        """AST 语法错误应触发重试，第二次成功"""
        from agents.supervisor.agent_executor import ClaudeCodeExecutor

        class ThenFixProvider:
            attempt = 0

            def complete(self, prompt, system_prompt="", **kwargs):
                ThenFixProvider.attempt += 1
                from tools.llm.base import LLMResponse
                if ThenFixProvider.attempt == 1:
                    # 第一次返回有语法错误的代码
                    return LLMResponse(content="def foo(\n  pass\n", success=True)
                # 第二次返回正确代码
                return LLMResponse(content="def foo():\n    pass\n", success=True)

        provider = ThenFixProvider()
        executor = ClaudeCodeExecutor(llm_provider=provider)
        code = executor.generate_code(
            spec={"interfaces": []},
            module_name="test_module",
            timeout=30.0,
        )
        assert "def foo" in code
        assert provider.attempt == 2

    def test_interface_consistency_check(self):
        """缺少接口时应触发重试"""
        from agents.supervisor.agent_executor import ClaudeCodeExecutor

        class FixInterfaceProvider:
            attempt = 0

            def complete(self, prompt, system_prompt="", **kwargs):
                FixInterfaceProvider.attempt += 1
                from tools.llm.base import LLMResponse
                if FixInterfaceProvider.attempt == 1:
                    # 没有 create_user 接口
                    return LLMResponse(content="def get_user(): pass\n", success=True)
                # 第二次加上了 create_user
                return LLMResponse(content="def get_user(): pass\ndef create_user(): pass\n", success=True)

        provider = FixInterfaceProvider()
        executor = ClaudeCodeExecutor(llm_provider=provider)
        code = executor.generate_code(
            spec={"interfaces": [{"name": "get_user"}, {"name": "create_user"}]},
            module_name="test_module",
            timeout=30.0,
        )
        assert "create_user" in code
        assert provider.attempt == 2

    def test_empty_response_returns_empty(self):
        """LLM 返回空内容时返回空字符串"""
        from agents.supervisor.agent_executor import ClaudeCodeExecutor

        class EmptyProvider:
            def complete(self, prompt, system_prompt="", **kwargs):
                from tools.llm.base import LLMResponse
                return LLMResponse(content="", success=True)

        executor = ClaudeCodeExecutor(llm_provider=EmptyProvider())
        code = executor.generate_code(
            spec={"interfaces": []},
            module_name="test_module",
            timeout=30.0,
        )
        assert code == ""

    def test_provider_exception_returns_empty(self):
        """Provider 抛异常时返回空字符串"""
        from agents.supervisor.agent_executor import ClaudeCodeExecutor

        class ErrorProvider:
            def complete(self, prompt, system_prompt="", **kwargs):
                raise RuntimeError("API Error: 429 Too Many Requests")

        executor = ClaudeCodeExecutor(llm_provider=ErrorProvider())
        code = executor.generate_code(
            spec={"interfaces": []},
            module_name="test_module",
            timeout=30.0,
        )
        assert code == ""

    def test_markdown_fence_stripping(self):
        """Markdown 代码围栏应被正确剥离"""
        from agents.supervisor.agent_executor import ClaudeCodeExecutor

        class MarkdownProvider:
            def complete(self, prompt, system_prompt="", **kwargs):
                from tools.llm.base import LLMResponse
                return LLMResponse(content="```python\ndef hello():\n    pass\n```", success=True)

        executor = ClaudeCodeExecutor(llm_provider=MarkdownProvider())
        code = executor.generate_code(
            spec={"interfaces": []},
            module_name="test_module",
            timeout=30.0,
        )
        assert not code.startswith("```")
        assert "def hello" in code


# ---------------------------------------------------------------------------
# _check_interface_consistency 单元测试
# ---------------------------------------------------------------------------

class TestCheckInterfaceConsistency:
    """接口一致性检查逻辑"""

    def test_all_interfaces_present(self):
        from agents.supervisor.agent_executor import ClaudeCodeExecutor
        code = "def login(): pass\ndef register(): pass\n"
        spec = {"interfaces": [{"name": "login"}, {"name": "register"}]}
        missing = ClaudeCodeExecutor._check_interface_consistency(code, spec, "auth")
        assert missing == []

    def test_some_interfaces_missing(self):
        from agents.supervisor.agent_executor import ClaudeCodeExecutor
        code = "def login(): pass\n"
        spec = {"interfaces": [{"name": "login"}, {"name": "register"}]}
        missing = ClaudeCodeExecutor._check_interface_consistency(code, spec, "auth")
        assert "register" in missing

    def test_no_interfaces_in_spec(self):
        from agents.supervisor.agent_executor import ClaudeCodeExecutor
        code = "x = 1\n"
        spec = {"interfaces": []}
        missing = ClaudeCodeExecutor._check_interface_consistency(code, spec, "test")
        assert missing == []

    def test_string_interfaces(self):
        from agents.supervisor.agent_executor import ClaudeCodeExecutor
        code = "def login(): pass\n"
        spec = {"interfaces": ["login", "register"]}
        missing = ClaudeCodeExecutor._check_interface_consistency(code, spec, "auth")
        assert "register" in missing


# ---------------------------------------------------------------------------
# CodexSupervisor.generate_code 测试（Mock）
# ---------------------------------------------------------------------------

class TestSupervisorGenerateCode:
    """CodexSupervisor.generate_code 测试"""

    def test_generate_code_delegates_to_executor(self):
        """generate_code 应委托给 ClaudeCodeExecutor"""
        from agents.supervisor import CodexSupervisor

        supervisor = CodexSupervisor(agents_config={})

        class FakeProvider:
            def complete(self, prompt, system_prompt="", **kwargs):
                from tools.llm.base import LLMResponse
                return LLMResponse(content="def hello():\n    return 'world'\n", success=True)

        code = supervisor.generate_code(
            module_spec={"interfaces": []},
            llm_provider=FakeProvider(),
            module_name="test_module",
        )
        assert "def hello" in code

    def test_generate_code_with_timeout(self):
        """timeout 参数应传递到 executor"""
        from agents.supervisor import CodexSupervisor

        supervisor = CodexSupervisor(agents_config={})

        captured_kwargs = []

        class CapturingProvider:
            def complete(self, prompt, system_prompt="", **kwargs):
                captured_kwargs.append(kwargs)
                from tools.llm.base import LLMResponse
                return LLMResponse(content="x = 1\n", success=True)

        supervisor.generate_code(
            module_spec={"interfaces": []},
            llm_provider=CapturingProvider(),
            module_name="test_module",
            timeout=60.0,
        )
        # 验证调用成功（timeout 在线程层面控制）
        assert len(captured_kwargs) >= 1


# ---------------------------------------------------------------------------
# 真实 LLM 测试（需要 ANTHROPIC_API_KEY）
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
class TestRealLLMCodeGeneration:
    """真实 LLM 代码生成端到端测试（需要有效的 API key）"""

    def test_claude_code_executor_real_llm(self):
        """ClaudeCodeExecutor 用真实 LLM 生成可解析代码"""
        from agents.supervisor.agent_executor import ClaudeCodeExecutor
        from tools.llm import create_llm_provider

        provider = create_llm_provider("anthropic")
        executor = ClaudeCodeExecutor(llm_provider=provider)

        code = executor.generate_code(
            spec={
                "components": [
                    {"name": "AuthService", "type": "service", "description": "认证服务"},
                ],
                "interfaces": [
                    {"name": "login", "method": "POST", "path": "/auth/login"},
                    {"name": "register", "method": "POST", "path": "/auth/register"},
                ],
                "acceptance_criteria": ["用户可登录", "用户可注册"],
            },
            module_name="authentication",
            timeout=120.0,
        )
        assert len(code) > 0, "Generated code should not be empty"
        # 验证 AST 解析
        ast.parse(code)
        # 验证包含关键接口
        assert "login" in code.lower()
        assert "register" in code.lower()

    def test_supervisor_generate_code_real_llm(self):
        """CodexSupervisor.generate_code 真实 LLM 调用"""
        from agents.supervisor import CodexSupervisor
        from tools.llm import create_llm_provider

        provider = create_llm_provider("anthropic")
        supervisor = CodexSupervisor(agents_config={})

        code = supervisor.generate_code(
            module_spec={
                "components": [{"name": "Calculator", "type": "service", "description": "计算器"}],
                "interfaces": [{"name": "add", "method": "POST", "path": "/calc/add"}],
                "acceptance_criteria": ["支持加法运算"],
            },
            llm_provider=provider,
            module_name="calculator",
            timeout=120.0,
        )
        assert len(code) > 0
        ast.parse(code)
        assert "add" in code.lower()

    def test_mock_provider_unaffected_by_real_llm_changes(self):
        """Mock 路径不受真实 LLM 变更影响"""
        provider = create_llm_provider(backend="mock")
        response = provider.complete("分析 auth 模块", output_format="json")
        assert response.success is True
        assert isinstance(response.parsed, dict)
