# tests/integration/test_system_integration.py

"""
System Integration Test

Tests the ClaudeCodexMultiAgent entry point:
  - run_phase1: full pipeline from requirement to prompt
  - run_phase2: review loop with convergence
  - Expert agent wiring
  - Store population
"""

import os
import sys
import unittest
import importlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Force fresh import by clearing any cached modules
for key in list(sys.modules.keys()):
    if key.startswith("tools") or key == "claude_codex_multi_agent":
        del sys.modules[key]

# Import via the package's __init__.py
import __init__ as ccm_module

ClaudeCodexMultiAgent = ccm_module.ClaudeCodexMultiAgent


# Module names used by file (not mapped)
FILE_MODULE_NAMES = ["auth", "product", "cart", "order", "payment", "notification", "report"]


class TestClaudeCodexMultiAgent(unittest.TestCase):
    """Test the main system entry point"""

    def setUp(self):
        self.system = ClaudeCodexMultiAgent()

    def test_initialization(self):
        """System should initialize all components"""
        self.assertIsNotNone(self.system.compiler)
        self.assertIsNotNone(self.system.quality_evaluator)
        self.assertIsNotNone(self.system.message_bus)
        self.assertIsNotNone(self.system.requirement_store)
        self.assertIsNotNone(self.system.interface_store)
        self.assertIsNotNone(self.system.spec_store)
        self.assertIsNotNone(self.system.supervisor)
        self.assertGreater(len(self.system.expert_agents), 0)

    def test_expert_agents_loaded(self):
        """Expert agents should be loaded from schemas"""
        for module in FILE_MODULE_NAMES:
            self.assertIn(
                module, self.system.expert_agents,
                f"Expert agent for '{module}' not loaded"
            )

    def test_run_phase1_returns_compiled_pipeline(self):
        """Phase 1 should return compiled pipeline with all components"""
        result = self.system.run_phase1(
            "构建一个在线商城，支持用户注册登录、商品浏览、购物车、下单和支付"
        )

        self.assertIn("compiled", result)
        self.assertIn("module_specs", result)
        self.assertIn("prompt", result)

        compiled = result["compiled"]
        self.assertEqual(len(compiled.context_strategies), 7)
        self.assertEqual(len(compiled.implementation_order), 7)

    def test_run_phase1_populates_stores(self):
        """Phase 1 should populate spec store"""
        self.system.run_phase1("构建在线商城")

        # Spec store should have entries
        self.assertGreater(len(self.system.spec_store), 0)

    def test_run_phase1_context_strategies_correct(self):
        """Phase 1 should derive correct context strategies"""
        result = self.system.run_phase1("构建在线商城")
        compiled = result["compiled"]

        # Authentication should need security context
        auth = compiled.context_strategies["auth"]
        self.assertTrue(auth.needs_security_context)

        # Payment should need compliance context
        pay = compiled.context_strategies["payment"]
        self.assertTrue(pay.needs_compliance_context)

        # Notification should NOT need security context
        notif = compiled.context_strategies["notification"]
        self.assertFalse(notif.needs_security_context)

    def test_run_phase1_prompt_generated(self):
        """Phase 1 should generate a non-empty prompt"""
        result = self.system.run_phase1("构建在线商城")
        prompt = result["prompt"]

        self.assertIsInstance(prompt, str)
        self.assertGreater(len(prompt), 100)
        self.assertIn("项目", prompt)
        self.assertIn("验收标准", prompt)

    def test_run_phase2_all_pass(self):
        """Phase 2 with all-pass reviews should converge quickly"""
        result = self.system.run_phase2("code_artifact")

        self.assertIn("passed", result)
        self.assertIn("quality_score", result)
        self.assertIn("iterations", result)
        self.assertIn("convergence_status", result)

    def test_run_phase2_convergence_detection(self):
        """Phase 2 should detect convergence"""
        result = self.system.run_phase2("code_artifact")

        # Should converge within max iterations
        self.assertLessEqual(result["iterations"], 3)

    def test_compile_pipeline_method(self):
        """compile_pipeline should work standalone"""
        compiled = self.system.compile_pipeline(
            self.system.compiler.compile_from_config().module_schemas
        )
        self.assertIsNotNone(compiled)

    def test_full_two_phase_flow(self):
        """Complete phase1 -> phase2 flow"""
        # Phase 1
        phase1_result = self.system.run_phase1("构建在线商城")
        self.assertIsNotNone(phase1_result["compiled"])

        # Phase 2
        phase2_result = self.system.run_phase2(
            "code_artifact",
            compiled_pipeline=phase1_result["compiled"],
        )

        self.assertIsNotNone(phase2_result)
        self.assertIn("convergence_status", phase2_result)


class TestExpertAgentWiring(unittest.TestCase):
    """Test that expert agents are properly wired to compiler output"""

    def setUp(self):
        self.system = ClaudeCodexMultiAgent()

    def test_expert_validate_input(self):
        """Expert agent should validate input correctly"""
        expert = self.system.expert_agents["auth"]

        # Valid input (has required fields from auth_input.json)
        valid = {"requirement": "test", "constraints": [], "dependencies": []}
        self.assertTrue(expert.validate_input(valid))

        # Invalid input (missing required field)
        invalid = {"constraints": []}
        self.assertFalse(expert.validate_input(invalid))

    def test_expert_validate_output(self):
        """Expert agent should validate output correctly"""
        expert = self.system.expert_agents["auth"]

        # Valid output (has module_spec with required fields)
        valid = {
            "module_spec": {
                "components": [],
                "interfaces": [],
                "acceptance_criteria": [],
            }
        }
        self.assertTrue(expert.validate_output(valid))

        # Invalid output (missing module_spec)
        invalid = {"confidence": 0.9}
        self.assertFalse(expert.validate_output(invalid))

    def test_expert_has_schemas(self):
        """Expert agents should have input/output schemas loaded"""
        for module in FILE_MODULE_NAMES:
            expert = self.system.expert_agents[module]
            self.assertIsNotNone(expert.input_schema)
            self.assertIsNotNone(expert.output_schema)


if __name__ == "__main__":
    unittest.main()
