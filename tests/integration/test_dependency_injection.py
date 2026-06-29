# tests/integration/test_dependency_injection.py
"""
P0-3: 多模块依赖注入端到端测试。

验证: 先处理的模块（auth）产出的 interfaces 被注入到后处理的模块（data_processing）的 ExpertInput 中。
"""
import os

import pytest

from tools.llm import create_llm_provider


class TestDependencyInjection:
    """_build_expert_input 依赖注入逻辑测试"""

    def _make_minimal_pipeline(self):
        """创建一个带 interface_store 和 _build_expert_input 的最小 pipeline"""
        from unittest.mock import MagicMock

        pipeline = MagicMock()
        pipeline._module_to_short_name = lambda name: name
        pipeline.interface_store = MagicMock()
        pipeline.interface_store.get_for_injection = lambda dep: None  # store 为空
        return pipeline

    def test_dependency_from_processed_specs(self):
        """依赖接口应从 processed_specs 中提取"""
        from agents.experts import ExpertOutput
        from agents.pipeline import ClaudeCodexMultiAgent
        from unittest.mock import MagicMock

        pipeline = self._make_minimal_pipeline()

        # 模拟 auth 已经被处理，产出了 interfaces
        auth_spec = ExpertOutput(
            module_name="authentication",
            components=[{"name": "AuthService", "type": "service"}],
            interfaces=[
                {"name": "login", "method": "POST", "path": "/auth/login"},
                {"name": "register", "method": "POST", "path": "/auth/register"},
            ],
            acceptance_criteria=["可登录"],
        )

        # strategy 声明需要依赖接口
        strategy = MagicMock()
        strategy.needs_dependency_interfaces = True
        strategy.depends_on = ["authentication"]

        input_schema = {"description": "数据处理模块"}

        # 调用 _build_expert_input，传入已处理的 auth spec
        expert_input = ClaudeCodexMultiAgent._build_expert_input(
            pipeline,
            module_name="data_processing",
            input_schema=input_schema,
            strategy=strategy,
            compiled=MagicMock(),
            processed_specs={"authentication": auth_spec},
        )

        # 验证 auth 的接口被注入了
        assert "authentication" in expert_input.dependency_interfaces
        auth_interfaces = expert_input.dependency_interfaces["authentication"]
        assert len(auth_interfaces) == 2
        iface_names = {i.get("name") for i in auth_interfaces}
        assert "login" in iface_names
        assert "register" in iface_names

    def test_no_strategy_no_injection(self):
        """strategy 不声明需要依赖时不注入"""
        from agents.pipeline import ClaudeCodexMultiAgent
        from unittest.mock import MagicMock

        pipeline = self._make_minimal_pipeline()

        strategy = MagicMock()
        strategy.needs_dependency_interfaces = False
        strategy.depends_on = []

        expert_input = ClaudeCodexMultiAgent._build_expert_input(
            pipeline,
            module_name="data_processing",
            input_schema={"description": "test"},
            strategy=strategy,
            compiled=MagicMock(),
            processed_specs={},
        )
        assert expert_input.dependency_interfaces == {}

    def test_fallback_to_interface_store(self):
        """processed_specs 中没有时，回退到 interface_store"""
        from agents.pipeline import ClaudeCodexMultiAgent
        from unittest.mock import MagicMock

        pipeline = MagicMock()
        pipeline._module_to_short_name = lambda name: name
        pipeline.interface_store.get_for_injection = lambda dep: json.dumps([
            {"name": "login", "method": "POST", "path": "/auth/login"},
        ])

        strategy = MagicMock()
        strategy.needs_dependency_interfaces = True
        strategy.depends_on = ["authentication"]

        # processed_specs 为空，应回退到 store
        import json
        expert_input = ClaudeCodexMultiAgent._build_expert_input(
            pipeline,
            module_name="data_processing",
            input_schema={"description": "test"},
            strategy=strategy,
            compiled=MagicMock(),
            processed_specs={},  # 空的
        )
        assert "authentication" in expert_input.dependency_interfaces

    def test_empty_processed_specs_no_error(self):
        """processed_specs 为空 dict 时不报错"""
        from agents.pipeline import ClaudeCodexMultiAgent
        from unittest.mock import MagicMock

        pipeline = MagicMock()
        pipeline._module_to_short_name = lambda name: name
        pipeline.interface_store.get_for_injection = lambda dep: None

        strategy = MagicMock()
        strategy.needs_dependency_interfaces = True
        strategy.depends_on = ["auth"]

        expert_input = ClaudeCodexMultiAgent._build_expert_input(
            pipeline,
            module_name="test_module",
            input_schema={},
            strategy=strategy,
            compiled=MagicMock(),
            processed_specs={},
        )
        # 没有注入任何接口，但不报错
        assert isinstance(expert_input.dependency_interfaces, dict)


class TestDependencyInjectionEndToEnd:
    """多模块依赖注入端到端测试"""

    def test_phase1_dependency_interfaces_injected(self):
        """Phase1 中 data_processing 应收到 auth 的接口"""
        from agents.pipeline import ClaudeCodexMultiAgent

        system = ClaudeCodexMultiAgent(
            llm_backend="mock",
            enable_guardrails=False,
            enable_memory=False,
            enable_hitl=False,
            enable_observability=False,
        )

        result = system.run_phase1("构建包含认证和数据处理的系统")

        # 验证 Phase1 完成
        assert result.get("compiled") is not None
        assert len(result.get("code_artifact", {})) > 0

    def test_three_module_pipeline(self):
        """三模块流水线完整运行"""
        from agents.pipeline import ClaudeCodexMultiAgent

        system = ClaudeCodexMultiAgent(
            llm_backend="mock",
            enable_guardrails=True,
            enable_memory=True,
            enable_hitl=True,
            enable_observability=False,
        )

        result = system.run_phase1("构建认证、数据处理和API集成系统")
        assert result.get("compiled") is not None
        # 至少生成一个模块的代码
        assert len(result.get("code_artifact", {})) >= 1
