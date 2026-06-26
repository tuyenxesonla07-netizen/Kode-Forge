# tests/integration/test_e2e_pipeline.py

"""
端到端集成测试 — 验证完整的编译流水线
"""

import os
import sys
import json
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tools.compiler.pipeline_compiler import PipelineCompiler, CompiledPipeline
from tools.messaging import MessageBus, Message
from tools.quality import ConvergenceDetector


# 模块文件名 → 模块名的映射
MODULE_NAME_MAP = {
    "auth": "authentication",
    "product": "product_catalog",
    "cart": "shopping_cart",
    "order": "order_system",
    "payment": "payment_integration",
    "notification": "notification_service",
    "report": "data_reporting",
}


class TestEndToEndPipeline(unittest.TestCase):
    """端到端编译流水线测试"""

    def setUp(self):
        self.schemas_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "schemas"
        )
        self.compiler = PipelineCompiler()

    def _load_all_output_schemas(self) -> dict:
        """加载所有 output_schema，使用正确的模块名"""
        schemas = {}
        for filename in os.listdir(self.schemas_dir):
            if filename.endswith("_output.json"):
                file_module = filename.replace("_output.json", "")
                module_name = MODULE_NAME_MAP.get(file_module, file_module)
                path = os.path.join(self.schemas_dir, filename)
                with open(path, encoding="utf-8") as f:
                    schemas[module_name] = json.load(f)
        return schemas

    def _load_all_input_schemas(self) -> dict:
        """加载所有 input_schema，使用正确的模块名"""
        schemas = {}
        for filename in os.listdir(self.schemas_dir):
            if filename.endswith("_input.json"):
                file_module = filename.replace("_input.json", "")
                module_name = MODULE_NAME_MAP.get(file_module, file_module)
                path = os.path.join(self.schemas_dir, filename)
                with open(path, encoding="utf-8") as f:
                    schemas[module_name] = json.load(f)
        return schemas

    def test_compile_all_modules(self):
        """编译所有 7 个模块"""
        module_schemas = self._load_all_output_schemas()
        input_schemas = self._load_all_input_schemas()
        compiled = self.compiler.compile(module_schemas, input_schemas=input_schemas)

        self.assertIsInstance(compiled, CompiledPipeline)
        self.assertEqual(len(compiled.module_schemas), 7)
        self.assertEqual(len(compiled.implementation_order), 7)

    def test_compilation_order(self):
        """编译结果应包含正确的拓扑排序"""
        module_schemas = self._load_all_output_schemas()
        input_schemas = self._load_all_input_schemas()
        compiled = self.compiler.compile(module_schemas, input_schemas=input_schemas)

        order = compiled.implementation_order
        # 所有 7 个模块都应该在排序中
        self.assertEqual(len(order), 7)
        self.assertIn("authentication", order)
        self.assertIn("order_system", order)
        self.assertIn("payment_integration", order)

    def test_context_strategies_derived(self):
        """上下文策略应自动推导"""
        module_schemas = self._load_all_output_schemas()
        input_schemas = self._load_all_input_schemas()
        compiled = self.compiler.compile(module_schemas, input_schemas=input_schemas)

        # 认证模块应有安全上下文
        auth_strategy = compiled.context_strategies.get("authentication")
        self.assertIsNotNone(auth_strategy)
        self.assertTrue(auth_strategy.needs_security_context)

        # 支付模块应有合规上下文
        pay_strategy = compiled.context_strategies.get("payment_integration")
        self.assertIsNotNone(pay_strategy)
        self.assertTrue(pay_strategy.needs_compliance_context)

    def test_fix_templates_derived(self):
        """修复模板应自动推导"""
        module_schemas = self._load_all_output_schemas()
        input_schemas = self._load_all_input_schemas()
        compiled = self.compiler.compile(module_schemas, input_schemas=input_schemas)

        self.assertEqual(len(compiled.fix_templates), 7)

        # 订单模块有状态机修复规则
        order_fix = compiled.fix_templates["order_system"]
        fix_types = [r.fix_type for r in order_fix.rules]
        self.assertIn("fix_state_machine", fix_types)

        # 购物车模块没有
        cart_fix = compiled.fix_templates["shopping_cart"]
        fix_types = [r.fix_type for r in cart_fix.rules]
        self.assertNotIn("fix_state_machine", fix_types)

    def test_quality_gates_generated(self):
        """质量门禁应自动生成"""
        module_schemas = self._load_all_output_schemas()
        compiled = self.compiler.compile(module_schemas)

        self.assertGreater(len(compiled.quality_gates.gates), 0)

        gate_names = [g.name for g in compiled.quality_gates.gates]
        self.assertIn("all_modules_pass_review", gate_names)
        self.assertIn("no_critical_issues", gate_names)
        # 质量门禁使用模块名作为前缀
        self.assertIn("order_system_state_machine_complete", gate_names)

    def test_to_superpowers_config(self):
        """应能转换为 Superpowers 配置"""
        module_schemas = self._load_all_output_schemas()
        compiled = self.compiler.compile(module_schemas)

        config = compiled.to_superpowers_config()

        self.assertIn("version", config)
        self.assertIn("pipeline", config)
        self.assertIn("phases", config["pipeline"])

    def test_compilation_report(self):
        """编译报告应包含所有关键信息"""
        module_schemas = self._load_all_output_schemas()
        compiled = self.compiler.compile(module_schemas)

        report = compiled.explain()

        self.assertIn("Pipeline Compilation Report", report)
        self.assertIn("authentication", report)
        self.assertIn("order_system", report)
        self.assertIn("Context Injection Strategies", report)
        self.assertIn("Fix Template Summary", report)
        self.assertIn("Quality Gates", report)


class TestQualityGateEvaluation(unittest.TestCase):
    """质量门禁评估测试"""

    def test_all_pass(self):
        """全部通过"""
        from tools.compiler.quality_gate_gen import QualityGateGenerator

        generator = QualityGateGenerator()
        module_schemas = {}
        for module in ["authentication", "order_system", "payment_integration"]:
            file_module = {
                "authentication": "auth",
                "order_system": "order",
                "payment_integration": "payment",
            }[module]
            path = os.path.join(
                os.path.dirname(__file__), "..", "..", "config", "schemas",
                f"{file_module}_output.json"
            )
            with open(path, encoding="utf-8") as f:
                module_schemas[module] = json.load(f)

        suite = generator.generate(module_schemas)

        metrics = {
            "all_modules_passed": True,
            "critical_issues_count": 0,
            "interface_consistency": True,
            "quality_score": 0.9,
            "test_coverage": 0.85,
            "security_score": 0.95,
            "authentication_acceptance_met": True,
            "order_system_acceptance_met": True,
            "payment_integration_acceptance_met": True,
            "order_system_state_machine_complete": True,
            "authentication_compliant": True,
            "order_system_compliant": True,
            "payment_integration_compliant": True,
        }

        result = suite.evaluate(metrics)
        self.assertTrue(result["passed"])

    def test_critical_issue_fails(self):
        """有 critical 问题应失败"""
        from tools.compiler.quality_gate_gen import QualityGateGenerator

        generator = QualityGateGenerator()
        path = os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "schemas",
            "auth_output.json"
        )
        with open(path, encoding="utf-8") as f:
            module_schemas = {"authentication": json.load(f)}

        suite = generator.generate(module_schemas)

        metrics = {
            "all_modules_passed": True,
            "critical_issues_count": 1,
            "interface_consistency": True,
            "quality_score": 0.9,
            "test_coverage": 0.85,
            "security_score": 0.95,
        }

        result = suite.evaluate(metrics)
        self.assertFalse(result["passed"])


class TestConvergenceDetector(unittest.TestCase):
    """收敛检测器测试"""

    def test_continue_on_first_iteration(self):
        """第一次迭代应继续"""
        detector = ConvergenceDetector()
        should_continue, reason = detector.should_continue(
            iteration=0, quality_score=0.6, has_critical=False
        )
        self.assertTrue(should_continue)

    def test_stop_when_quality_sufficient(self):
        """质量达标应停止"""
        detector = ConvergenceDetector()
        should_continue, reason = detector.should_continue(
            iteration=0, quality_score=0.85, has_critical=False
        )
        self.assertFalse(should_continue)
        self.assertIn("达标", reason)

    def test_stop_at_max_iterations(self):
        """达到最大迭代次数应停止"""
        detector = ConvergenceDetector(max_iterations=3)
        detector.record_score(0.6)
        detector.record_score(0.65)
        detector.record_score(0.68)

        should_continue, reason = detector.should_continue(
            iteration=3, quality_score=0.68, has_critical=False
        )
        self.assertFalse(should_continue)
        self.assertIn("最大迭代", reason)

    def test_stop_when_stagnant(self):
        """连续 2 次未提升应停止"""
        detector = ConvergenceDetector()
        detector.record_score(0.6)
        detector.record_score(0.6)
        detector.record_score(0.6)

        should_continue, reason = detector.should_continue(
            iteration=2, quality_score=0.6, has_critical=False
        )
        self.assertFalse(should_continue)
        self.assertIn("未提升", reason)

    def test_stop_on_critical(self):
        """有 critical 问题应停止"""
        detector = ConvergenceDetector()
        should_continue, reason = detector.should_continue(
            iteration=0, quality_score=0.7, has_critical=True
        )
        self.assertFalse(should_continue)
        self.assertIn("critical", reason)


class TestMessageBus(unittest.TestCase):
    """消息总线测试"""

    def test_publish_and_receive(self):
        """发布和接收"""
        bus = MessageBus()
        msg = Message.create(
            from_agent="codex",
            to_agent="expert_auth",
            phase="requirement_decomposition",
            payload_type="task",
            payload={"task_id": "T001", "module": "auth"},
        )

        bus.publish(msg)
        received = bus.receive("expert_auth", timeout_ms=100)

        self.assertIsNotNone(received)
        self.assertEqual(received.msg_id, msg.msg_id)

    def test_subscribe_topic(self):
        """订阅 topic"""
        bus = MessageBus()
        received_messages = []

        def handler(msg):
            received_messages.append(msg)

        bus.subscribe("events.pipeline", handler)

        msg = Message.create(
            from_agent="superpowers",
            to_agent="broadcast",
            phase="requirement_decomposition",
            payload_type="event",
            payload={"event": "task_completed"},
        )
        bus.publish("events.pipeline", msg)

        self.assertEqual(len(received_messages), 1)

    def test_history(self):
        bus = MessageBus()

        for i in range(5):
            msg = Message.create(
                from_agent="codex",
                to_agent="expert_auth",
                phase="test",
                payload_type="task",
                payload={"task_id": f"T{i:03d}"},
            )
            bus.publish(msg)

        history = bus.get_history("codex", limit=3)
        self.assertEqual(len(history), 3)


if __name__ == "__main__":
    unittest.main()

