# tests/integration/test_pipeline_integration.py
"""
Pipeline Integration Tests

端到端系统流测试，验证 ClaudeCodexMultiAgent 入口点的完整流程：
  - Phase 1: 需求 → 编译 → 专家分析 → 代码生成
  - Phase 2: 审查 → 收敛检测
  - 专家 Agent 接线
  - Store 填充
"""

import os
import sys
import unittest
import importlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Import the package __init__ via importlib
spec = importlib.util.spec_from_file_location(
    "claude_codex_multi_agent",
    os.path.join(os.path.dirname(__file__), "..", "..", "__init__.py"),
)
ccm_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ccm_module)
# After exec, sys.modules[__name__] may be a _LazyModule proxy
_ccm = sys.modules.get("claude_codex_multi_agent", ccm_module)
ClaudeCodexMultiAgent = _ccm.ClaudeCodexMultiAgent


# 完整名称 (expert_agents keys)
FILE_MODULE_NAMES = ["authentication", "data_processing", "api_integration"]


class TestClaudeCodexMultiAgent(unittest.TestCase):
    """主系统入口测试"""

    def setUp(self):
        self.system = ClaudeCodexMultiAgent()

    def test_initialization(self):
        """系统应初始化所有组件"""
        self.assertIsNotNone(self.system.compiler)
        self.assertIsNotNone(self.system.quality_evaluator)
        self.assertIsNotNone(self.system.message_bus)
        self.assertIsNotNone(self.system.requirement_store)
        self.assertIsNotNone(self.system.interface_store)
        self.assertIsNotNone(self.system.spec_store)
        self.assertIsNotNone(self.system.supervisor)
        self.assertGreater(len(self.system.expert_agents), 0)

    def test_expert_agents_loaded(self):
        """专家 Agent 应从 schemas 加载"""
        for module in FILE_MODULE_NAMES:
            self.assertIn(
                module, self.system.expert_agents,
                f"Expert agent for '{module}' not loaded"
            )

    def test_run_phase1_full_flow(self):
        """Phase 1: 编译 → 上下文 → 专家 → Prompt"""
        result = self.system.run_phase1(
            "构建一个在线商城，支持用户注册登录、商品浏览、购物车、下单和支付"
        )

        self.assertIn("compiled", result)
        self.assertIn("module_specs", result)
        self.assertIn("prompt", result)

        compiled = result["compiled"]
        self.assertEqual(len(compiled.context_strategies), 3)
        self.assertEqual(len(compiled.implementation_order), 3)

    def test_run_phase1_populates_stores(self):
        """Phase 1 应填充 spec store"""
        self.system.run_phase1("构建在线商城")
        self.assertGreater(len(self.system.spec_store), 0)

    def test_run_phase1_context_strategies_correct(self):
        """Phase 1 应推导正确的上下文策略"""
        result = self.system.run_phase1("Build authentication module with JWT and OAuth2")
        compiled = result["compiled"]

        # authentication with security keywords needs security context
        auth = compiled.context_strategies["authentication"]
        self.assertTrue(auth.needs_security_context)

        # context strategies are derived per module
        for name, strategy in compiled.context_strategies.items():
            self.assertIsInstance(strategy.depends_on, list)
            self.assertIsInstance(strategy.needs_security_context, bool)

    def test_run_phase1_prompt_generated(self):
        """Phase 1 应生成非空 Prompt（包含验收标准）"""
        result = self.system.run_phase1("构建在线商城")
        prompt = result["prompt"]

        self.assertIsInstance(prompt, str)
        self.assertGreater(len(prompt), 100)
        self.assertIn("验收标准", prompt)

    def test_run_phase2_all_pass(self):
        """Phase 2: 全部通过的审查应快速收敛"""
        phase1 = self.system.run_phase1("Build auth module")
        result = self.system.run_phase2(
            phase1.get("code_artifact", {}),
            compiled_pipeline=phase1.get("compiled"),
        )

        self.assertIn("passed", result)
        self.assertIn("quality_score", result)
        self.assertIn("iterations", result)
        self.assertIn("convergence_status", result)

    def test_run_phase2_convergence_detection(self):
        """Phase 2 应检测收敛"""
        phase1 = self.system.run_phase1("Build auth module")
        result = self.system.run_phase2(
            phase1.get("code_artifact", {}),
            compiled_pipeline=phase1.get("compiled"),
        )

        self.assertLessEqual(result["iterations"], 3)

    def test_compile_pipeline_method(self):
        """compile_pipeline 应能独立工作"""
        compiled = self.system.compile_pipeline(
            self.system.compiler.compile_from_config().module_schemas
        )
        self.assertIsNotNone(compiled)

    def test_full_two_phase_flow(self):
        """完整的 Phase 1 → Phase 2 流程"""
        # Phase 1
        phase1_result = self.system.run_phase1("构建在线商城")
        self.assertIsNotNone(phase1_result["compiled"])

        # Phase 2 — 使用 Phase1 生成的真实代码
        phase2_result = self.system.run_phase2(
            phase1_result["code_artifact"],
            compiled_pipeline=phase1_result["compiled"],
        )

        self.assertIsNotNone(phase2_result)
        self.assertIn("convergence_status", phase2_result)


class TestExpertAgentWiring(unittest.TestCase):
    """专家 Agent 接线测试"""

    def setUp(self):
        self.system = ClaudeCodexMultiAgent()

    def test_expert_validate_input(self):
        """专家 Agent 应正确验证输入"""
        expert = self.system.expert_agents["authentication"]

        # 有效输入
        valid = {"requirement": "test", "constraints": [], "dependencies": []}
        self.assertTrue(expert.validate_input(valid))

        # 无效输入
        invalid = {"constraints": []}
        self.assertFalse(expert.validate_input(invalid))

    def test_expert_validate_output(self):
        """专家 Agent 应正确验证输出"""
        expert = self.system.expert_agents["authentication"]

        # 有效输出
        valid = {
            "module_spec": {
                "components": [],
                "interfaces": [],
                "acceptance_criteria": [],
            }
        }
        self.assertTrue(expert.validate_output(valid))

        # 无效输出
        invalid = {"confidence": 0.9}
        self.assertFalse(expert.validate_output(invalid))

    def test_expert_has_schemas(self):
        """专家 Agent 应加载 input/output schema"""
        for module in FILE_MODULE_NAMES:
            expert = self.system.expert_agents[module]
            self.assertIsNotNone(expert.input_schema)
            self.assertIsNotNone(expert.output_schema)


if __name__ == "__main__":
    unittest.main()
