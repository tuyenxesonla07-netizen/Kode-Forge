"""
tests/compiler/test_fix_deriver.py

修复指令推导器测试 — 验证 Schema → FixTemplate 的自动推导
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tools.compiler.fix_deriver import FixInstructionDeriver


class TestFixInstructionDeriver(unittest.TestCase):
    """测试修复指令推导器"""

    def setUp(self):
        self.deriver = FixInstructionDeriver()
        self.schemas_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "schemas"
        )

    def _load_schema(self, filename: str) -> dict:
        import json
        path = os.path.join(self.schemas_dir, filename)
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def test_data_processing_has_state_machine_rule(self):
        """数据处理模块应有状态机修复规则"""
        schema = self._load_schema("data_processing_output.json")
        template = self.deriver.derive("data_processing", schema)

        fix_types = [r.fix_type for r in template.rules]
        self.assertIn("fix_state_machine", fix_types)

    def test_auth_has_security_rule(self):
        """认证模块应有安全修复规则"""
        schema = self._load_schema("authentication_output.json")
        template = self.deriver.derive("authentication", schema)

        fix_types = [r.fix_type for r in template.rules]
        self.assertIn("fix_security", fix_types)

    def test_api_integration_has_security_rule(self):
        """API 集成模块应有安全修复规则"""
        schema = self._load_schema("api_integration_output.json")
        template = self.deriver.derive("api_integration", schema)

        fix_types = [r.fix_type for r in template.rules]
        self.assertIn("fix_security", fix_types)

    def test_data_processing_has_state_machine_rule(self):
        """数据处理模块应有状态机修复规则"""
        schema = self._load_schema("data_processing_output.json")
        template = self.deriver.derive("data_processing", schema)

        fix_types = [r.fix_type for r in template.rules]
        self.assertIn("fix_state_machine", fix_types)

    def test_api_integration_has_no_state_machine_rule(self):
        """API 集成模块不应有状态机修复规则"""
        schema = self._load_schema("api_integration_output.json")
        template = self.deriver.derive("api_integration", schema)

        fix_types = [r.fix_type for r in template.rules]
        self.assertNotIn("fix_state_machine", fix_types)

    def test_all_modules_have_add_component_rule(self):
        """所有模块都应有组件修复规则"""
        for module in ["authentication", "data_processing", "api_integration"]:
            schema = self._load_schema(f"{module}_output.json")
            template = self.deriver.derive(module, schema)

            fix_types = [r.fix_type for r in template.rules]
            self.assertIn("add_component", fix_types,
                          f"{module} should have add_component rule")

    def test_generate_fix_instructions(self):
        """测试从问题生成修复指令"""
        schema = self._load_schema("data_processing_output.json")
        template = self.deriver.derive("data_processing", schema)

        issues = [
            {
                "issue_id": "I001",
                "severity": "major",
                "location": "data_processing/service.py:42",
                "description": "状态机转换无效: pending -> cancelled",
                "from": "pending",
                "to": "cancelled",
                "trigger": "cancel_order",
                "validation": "状态转换应正确执行",
            }
        ]

        instructions = template.generate_fix_instructions(issues)

        self.assertTrue(len(instructions) > 0)
        inst = instructions[0]
        self.assertEqual(inst["module"], "data_processing")
        self.assertEqual(inst["fix_type"], "fix_state_machine")
        self.assertIn("I001", inst["issue_id"])

    def test_fix_template_metadata(self):
        """修复模板应包含正确的元数据"""
        schema = self._load_schema("data_processing_output.json")
        template = self.deriver.derive("data_processing", schema)

        self.assertTrue(template.metadata["has_state_machine_rule"])
        self.assertEqual(template.metadata["derived_from"], "data_processing_output.json")

    def test_derive_all_modules(self):
        """批量推导所有模块"""
        schemas = {}
        for module in ["authentication", "data_processing", "api_integration"]:
            schemas[module] = self._load_schema(f"{module}_output.json")

        templates = self.deriver.derive_all(schemas)

        self.assertEqual(len(templates), 3)
        # API 集成有安全规则
        self.assertTrue(templates["api_integration"].metadata["has_security_rule"])
        # 数据处理没有
        self.assertFalse(templates["data_processing"].metadata["has_security_rule"])


if __name__ == "__main__":
    unittest.main()

