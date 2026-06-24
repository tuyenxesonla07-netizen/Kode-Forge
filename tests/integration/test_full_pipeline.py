# tests/integration/test_full_pipeline.py

"""
Full Pipeline Integration Test

Tests the complete flow: compile -> context injection -> expert analysis
-> prompt generation -> code review -> fix loop -> convergence

This test wires together all major components:
  PipelineCompiler + ContextDeriver + FixInstructionDeriver
  + QualityEvaluator + ConvergenceDetector + MessageBus
"""

import os
import sys
import json
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tools.compiler import (
    PipelineCompiler,
    ContextDeriver,
    FixInstructionDeriver,
    PromptTemplateGenerator,
    QualityGateGenerator,
)
from tools.stores import RequirementStore, InterfaceStore, SpecStore
from tools.messaging import MessageBus, Message, Topic
from tools.quality import QualityEvaluator, ReviewResult, ConvergenceDetector


class TestFullPipeline(unittest.TestCase):
    """Full pipeline integration test"""

    def setUp(self):
        self.schemas_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "schemas"
        )
        self.compiler = PipelineCompiler()
        self.evaluator = QualityEvaluator()
        self.bus = MessageBus()

    def _load_schemas(self):
        """Load all schemas from config directory"""
        MODULE_NAME_MAP = {
            "auth": "authentication",
            "product": "product_catalog",
            "cart": "shopping_cart",
            "order": "order_system",
            "payment": "payment_integration",
            "notification": "notification_service",
            "report": "data_reporting",
        }

        input_schemas = {}
        output_schemas = {}

        for filename in os.listdir(self.schemas_dir):
            path = os.path.join(self.schemas_dir, filename)
            with open(path) as f:
                schema = json.load(f)

            if filename.endswith("_input.json"):
                file_module = filename.replace("_input.json", "")
                module = MODULE_NAME_MAP.get(file_module, file_module)
                input_schemas[module] = schema
            elif filename.endswith("_output.json"):
                file_module = filename.replace("_output.json", "")
                module = MODULE_NAME_MAP.get(file_module, file_module)
                output_schemas[module] = schema

        return input_schemas, output_schemas

    def test_phase1_full_flow(self):
        """Phase 1: compile -> context -> experts -> prompt"""
        input_schemas, output_schemas = self._load_schemas()

        # Compile pipeline
        compiled = self.compiler.compile(
            output_schemas, input_schemas=input_schemas
        )

        # Verify compilation results
        self.assertEqual(len(compiled.context_strategies), 7)
        self.assertEqual(len(compiled.implementation_order), 7)
        self.assertEqual(len(compiled.fix_templates), 7)
        self.assertGreater(len(compiled.quality_gates.gates), 0)

        # Verify context strategies are derived from input schemas
        auth_strategy = compiled.context_strategies["authentication"]
        self.assertTrue(auth_strategy.needs_security_context)
        self.assertIn("security_requirements", auth_strategy.injectable_fields)

        pay_strategy = compiled.context_strategies["payment_integration"]
        self.assertTrue(pay_strategy.needs_compliance_context)

        # Verify prompt template was generated
        prompt = compiled.prompt_template.template_str
        self.assertIn("项目", prompt)
        self.assertIn("实现顺序", prompt)
        self.assertIn("验收标准", prompt)

    def test_phase2_review_loop(self):
        """Phase 2: review -> evaluate -> fix -> converge"""
        _, output_schemas = self._load_schemas()
        compiled = self.compiler.compile(output_schemas)

        detector = ConvergenceDetector(max_iterations=3)
        iteration = 0

        while True:
            # Simulate reviews (all pass)
            review_results = [
                ReviewResult(module=m, verdict="pass")
                for m in compiled.implementation_order
            ]

            # Evaluate
            report = self.evaluator.evaluate(review_results, iteration=iteration)

            # Check convergence
            should_continue, reason = detector.should_continue(
                iteration=iteration,
                quality_score=report.quality_score,
                has_critical=report.has_critical,
            )

            if not should_continue:
                break

            iteration += 1

        # Should converge within 1-2 iterations for all-pass reviews
        self.assertLessEqual(iteration, 2)

    def test_fix_instruction_generation(self):
        """Test fix instructions are generated for failed reviews"""
        _, output_schemas = self._load_schemas()
        compiled = self.compiler.compile(output_schemas)

        # Simulate a failed review with issues
        review_results = [
            ReviewResult(
                module="order_system",
                verdict="fail",
                issues=[
                    {
                        "issue_id": "I001",
                        "severity": "major",
                        "location": "order/service.py:42",
                        "description": "状态机转换无效: pending -> cancelled",
                        "from": "pending",
                        "to": "cancelled",
                        "trigger": "cancel_order",
                    }
                ],
            )
        ]

        # Generate fix instructions
        fix_template = compiled.fix_templates["order_system"]
        instructions = fix_template.generate_fix_instructions(
            review_results[0].issues
        )

        self.assertEqual(len(instructions), 1)
        inst = instructions[0]
        self.assertEqual(inst["module"], "order_system")
        self.assertEqual(inst["fix_type"], "fix_state_machine")

    def test_message_bus_integration(self):
        """Test message bus is used for agent communication"""
        _, output_schemas = self._load_schemas()
        compiled = self.compiler.compile(output_schemas)

        # Track messages
        received = []
        self.bus.subscribe("results.order_system", lambda m: received.append(m))

        # Simulate publishing a result to the correct topic
        msg = Message.create(
            from_agent="expert_order",
            to_agent="superpowers",
            phase="requirement_decomposition",
            payload_type="result",
            payload={"module": "order_system", "status": "success"},
        )
        self.bus.publish("results.order_system", msg)

        self.assertEqual(len(received), 1)

    def test_stores_integration(self):
        """Test stores are populated during pipeline execution"""
        from tools.stores.interface_store import InterfaceDef

        input_schemas, output_schemas = self._load_schemas()

        req_store = RequirementStore()
        iface_store = InterfaceStore()
        spec_store = SpecStore()

        # Populate requirement store
        for module_name, schema in input_schemas.items():
            req_store.put(
                module_name,
                type("Req", (), {
                    "module_name": module_name,
                    "description": schema.get("description", ""),
                    "constraints": [],
                    "priority": 1,
                })(),
            )

        self.assertEqual(len(req_store), 7)

        # Populate interface store with proper InterfaceDef objects
        iface_store.register_module(
            "authentication",
            [
                InterfaceDef(
                    name="login",
                    method="POST",
                    path="/api/auth/login",
                    description="用户登录",
                ),
            ],
        )

        result = iface_store.get_for_injection("authentication")
        self.assertIsInstance(result, str)
        self.assertIn("login", result)

        # Populate spec store
        spec_store.put(
            "authentication",
            type("Spec", (), {
                "module_name": "authentication",
                "acceptance_criteria": ["Test 1"],
                "confidence": 0.9,
            })(),
        )

        self.assertEqual(len(spec_store), 1)
        self.assertAlmostEqual(spec_store.get_overall_confidence(), 0.9)

    def test_context_isolation(self):
        """Test that context strategies are isolated between modules"""
        input_schemas, output_schemas = self._load_schemas()
        compiled = self.compiler.compile(
            output_schemas, input_schemas=input_schemas
        )

        # Auth should have security context
        auth = compiled.context_strategies["authentication"]
        self.assertTrue(auth.needs_security_context)

        # Notification should NOT have security context
        notif = compiled.context_strategies["notification_service"]
        self.assertFalse(notif.needs_security_context)

        # Auth should NOT have compliance context
        self.assertFalse(auth.needs_compliance_context)

        # Payment should have compliance context
        pay = compiled.context_strategies["payment_integration"]
        self.assertTrue(pay.needs_compliance_context)

    def test_dependency_graph_with_agents_config(self):
        """Test dependency graph is built from agents.yaml when available"""
        import yaml

        agents_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "agents.yaml"
        )
        with open(agents_path, "r") as f:
            content = f.read()
            lines = content.split("\n")
            yaml_lines = []
            in_yaml = False
            for line in lines:
                if line.strip().startswith("```yaml"):
                    in_yaml = True
                    continue
                if line.strip() == "```" and in_yaml:
                    break
                if in_yaml:
                    yaml_lines.append(line)
            agents_config = yaml.safe_load("\n".join(yaml_lines))

        _, output_schemas = self._load_schemas()
        compiled = self.compiler.compile(output_schemas, agents_config=agents_config)

        # With agents.yaml, dependency graph should have edges
        order_idx = compiled.implementation_order.index("order_system")
        cart_idx = compiled.implementation_order.index("shopping_cart")

        # shopping_cart should come before order_system (it's a dependency)
        self.assertLess(cart_idx, order_idx)


if __name__ == "__main__":
    unittest.main()
