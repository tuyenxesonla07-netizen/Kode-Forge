# tests/integration/test_edge_cases.py

"""
Edge Case Tests

Tests boundary conditions, error handling, and unusual inputs.
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
    DependencyGraphBuilder,
    QualityGateGenerator,
)
from tools.compiler.dependency_graph import DependencyGraph
from tools.stores import RequirementStore, InterfaceStore, SpecStore
from tools.messaging import MessageBus
from tools.quality import QualityEvaluator, ReviewResult, ConvergenceDetector


class TestEmptyInputs(unittest.TestCase):
    """Test behavior with empty or minimal inputs"""

    def test_compile_empty_schemas(self):
        compiler = PipelineCompiler()
        compiled = compiler.compile({})
        self.assertEqual(len(compiled.module_schemas), 0)
        self.assertEqual(len(compiled.implementation_order), 0)

    def test_context_deriver_empty_schema(self):
        deriver = ContextDeriver()
        strategy = deriver.derive("test_module", {})
        self.assertFalse(strategy.needs_security_context)
        self.assertFalse(strategy.needs_compliance_context)
        self.assertTrue(strategy.needs_global_constraints)

    def test_fix_deriver_minimal_schema(self):
        deriver = FixInstructionDeriver()
        minimal_schema = {
            "properties": {
                "module_spec": {
                    "required": ["components", "acceptance_criteria"],
                    "properties": {
                        "components": {"items": {}},
                        "acceptance_criteria": {"items": {"type": "string"}},
                    },
                }
            }
        }
        template = deriver.derive("test", minimal_schema)
        self.assertEqual(len(template.rules), 4)

    def test_quality_evaluator_no_gates(self):
        evaluator = QualityEvaluator()
        results = [ReviewResult(module="test", verdict="pass")]
        report = evaluator.evaluate(results, iteration=0)
        self.assertIsNotNone(report)

    def test_convergence_detector_empty_history(self):
        detector = ConvergenceDetector()
        should_continue, reason = detector.should_continue(
            iteration=0, quality_score=0.5, has_critical=False
        )
        self.assertTrue(should_continue)


class TestSingleModule(unittest.TestCase):
    """Test with only one module"""

    def test_single_module_compile(self):
        compiler = PipelineCompiler()
        single_schema = {
            "authentication": {
                "properties": {
                    "module_spec": {
                        "required": ["components", "acceptance_criteria"],
                        "properties": {
                            "components": {"items": {}},
                            "acceptance_criteria": {"items": {"type": "string"}},
                        },
                    }
                }
            }
        }
        compiled = compiler.compile(single_schema)
        self.assertEqual(len(compiled.implementation_order), 1)
        self.assertIn("authentication", compiled.implementation_order)


class TestCircularDependencies(unittest.TestCase):
    """Test circular dependency detection"""

    def test_simple_cycle(self):
        graph = DependencyGraph()
        graph.add_module("a", ["b"])
        graph.add_module("b", ["a"])
        self.assertTrue(graph.has_cycle())

    def test_self_reference(self):
        graph = DependencyGraph()
        graph.add_module("a", ["a"])
        self.assertTrue(graph.has_cycle())

    def test_complex_cycle(self):
        graph = DependencyGraph()
        graph.add_module("a", ["b"])
        graph.add_module("b", ["c"])
        graph.add_module("c", ["a"])
        self.assertTrue(graph.has_cycle())

    def test_no_cycle(self):
        graph = DependencyGraph()
        graph.add_module("a", [])
        graph.add_module("b", ["a"])
        graph.add_module("c", ["b"])
        self.assertFalse(graph.has_cycle())

    def test_builder_validate(self):
        builder = DependencyGraphBuilder({})
        builder.build()
        is_valid, errors = builder.validate()
        self.assertTrue(is_valid)


class TestMessageBusEdgeCases(unittest.TestCase):
    """Test message bus edge cases"""

    def test_receive_empty_queue(self):
        bus = MessageBus()
        result = bus.receive("nonexistent", timeout_ms=100)
        self.assertIsNone(result)

    def test_subscribe_no_messages(self):
        bus = MessageBus()
        called = []
        bus.subscribe("test.topic", lambda m: called.append(m))
        self.assertEqual(len(called), 0)

    def test_multiple_subscribers(self):
        bus = MessageBus()
        received1 = []
        received2 = []
        bus.subscribe("test.topic", lambda m: received1.append(m))
        bus.subscribe("test.topic", lambda m: received2.append(m))
        bus.publish("test.topic", "message")
        self.assertEqual(len(received1), 1)
        self.assertEqual(len(received2), 1)

    def test_queue_stats(self):
        bus = MessageBus()
        bus.publish("agent1", "msg1")
        bus.publish("agent1", "msg2")
        stats = bus.get_stats()
        self.assertEqual(stats["total_messages"], 2)


class TestQualityGateEdgeCases(unittest.TestCase):
    """Test quality gate edge cases"""

    def test_all_gates_pass(self):
        generator = QualityGateGenerator()
        schema = {
            "test": {
                "properties": {
                    "module_spec": {
                        "required": ["components"],
                        "properties": {"components": {"items": {}}},
                    }
                }
            }
        }
        suite = generator.generate(schema)
        metrics = {
            "all_modules_passed": True,
            "critical_issues_count": 0,
            "interface_consistency": True,
            "quality_score": 0.9,
            "test_coverage": 0.8,
            "security_score": 0.95,
            "test_acceptance_met": True,
        }
        result = suite.evaluate(metrics)
        self.assertTrue(result["passed"])

    def test_critical_issue_fails_blocking(self):
        generator = QualityGateGenerator()
        schema = {}
        suite = generator.generate(schema)
        metrics = {
            "all_modules_passed": True,
            "critical_issues_count": 1,
            "interface_consistency": True,
            "quality_score": 0.9,
            "test_coverage": 0.8,
            "security_score": 0.95,
        }
        result = suite.evaluate(metrics)
        self.assertFalse(result["passed"])

    def test_advisory_gate_failure_doesnt_block(self):
        generator = QualityGateGenerator()
        schema = {}
        suite = generator.generate(schema)
        metrics = {
            "all_modules_passed": True,
            "critical_issues_count": 0,
            "interface_consistency": True,
            "quality_score": 0.9,
            "test_coverage": 0.5,
            "security_score": 0.95,
        }
        result = suite.evaluate(metrics)
        self.assertTrue(result["passed"])


class TestConvergenceEdgeCases(unittest.TestCase):
    """Test convergence detection edge cases"""

    def test_stagnant_scores(self):
        detector = ConvergenceDetector()
        detector.record_score(0.7)
        detector.record_score(0.7)
        detector.record_score(0.7)
        should_continue, reason = detector.should_continue(
            iteration=2, quality_score=0.7, has_critical=False
        )
        self.assertFalse(should_continue)

    def test_improving_scores_continue(self):
        detector = ConvergenceDetector()
        detector.record_score(0.5)
        detector.record_score(0.6)
        detector.record_score(0.7)
        should_continue, reason = detector.should_continue(
            iteration=2, quality_score=0.7, has_critical=False
        )
        self.assertTrue(should_continue)

    def test_max_iterations_reached(self):
        detector = ConvergenceDetector(max_iterations=2)
        should_continue, reason = detector.should_continue(
            iteration=2, quality_score=0.5, has_critical=False
        )
        self.assertFalse(should_continue)


if __name__ == "__main__":
    unittest.main()
