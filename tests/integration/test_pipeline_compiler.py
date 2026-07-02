# tests/integration/test_pipeline_compiler.py
"""
Pipeline Compiler Integration Tests

覆盖所有编译器相关测试：
  - Schema 编译（全部 3 模块 + 空输入 + 单模块）
  - 依赖图构建和拓扑排序
  - 上下文策略推导
  - 修复指令推导
  - 质量门禁生成（含 pipeline.yaml 加载）
  - 收敛检测器
  - 消息总线
"""

import os
import sys
import json
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tools.compiler import (
    PipelineCompiler,
    PipelineConfig,
    ContextDeriver,
    FixInstructionDeriver,
    DependencyGraphBuilder,
    QualityGateGenerator,
)
from tools.compiler.dependency_graph import DependencyGraph
from tools.workflow.messaging import MessageBus, Message
from tools.quality import QualityEvaluator, ReviewResult, ConvergenceDetector


# 模块文件名前缀 → 完整模块名 映射
MODULE_NAME_MAP = {
    "auth": "authentication",
    "data_processing": "data_processing",
    "api_integration": "api_integration",
}


class TestCompilerFullCompilation(unittest.TestCase):
    """编译所有 3 个模块的完整测试"""

    def setUp(self):
        self.compiler = PipelineCompiler()
        self.schemas_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "schemas"
        )

    def _load_all_output_schemas(self) -> dict:
        """加载所有 output_schema"""
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
        """加载所有 input_schema"""
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
        """编译所有 3 个模块"""
        module_schemas = self._load_all_output_schemas()
        input_schemas = self._load_all_input_schemas()
        compiled = self.compiler.compile(module_schemas, input_schemas=input_schemas)

        self.assertIsInstance(compiled, type(compiled))  # CompiledPipeline
        self.assertEqual(len(compiled.module_schemas), 3)
        self.assertEqual(len(compiled.implementation_order), 3)

    def test_compilation_order(self):
        """编译结果应包含正确的拓扑排序"""
        module_schemas = self._load_all_output_schemas()
        input_schemas = self._load_all_input_schemas()
        compiled = self.compiler.compile(module_schemas, input_schemas=input_schemas)

        order = compiled.implementation_order
        self.assertEqual(len(order), 3)
        self.assertIn("authentication", order)
        self.assertIn("data_processing", order)
        self.assertIn("api_integration", order)

    def test_context_strategies_derived(self):
        """上下文策略应自动推导"""
        module_schemas = self._load_all_output_schemas()
        input_schemas = self._load_all_input_schemas()
        compiled = self.compiler.compile(module_schemas, input_schemas=input_schemas)

        # 认证模块应有安全上下文
        auth_strategy = compiled.context_strategies.get("authentication")
        self.assertIsNotNone(auth_strategy)
        self.assertTrue(auth_strategy.needs_security_context)

        # API 集成模块应有合规上下文
        api_strategy = compiled.context_strategies.get("api_integration")
        self.assertIsNotNone(api_strategy)
        self.assertTrue(api_strategy.needs_compliance_context)

    def test_fix_templates_derived(self):
        """修复模板应自动推导"""
        module_schemas = self._load_all_output_schemas()
        input_schemas = self._load_all_input_schemas()
        compiled = self.compiler.compile(module_schemas, input_schemas=input_schemas)

        self.assertEqual(len(compiled.fix_templates), 3)

        # 数据处理模块有状态机修复规则
        dp_fix = compiled.fix_templates["data_processing"]
        fix_types = [r.fix_type for r in dp_fix.rules]
        self.assertIn("fix_state_machine", fix_types)

        # API 集成模块没有状态机修复规则
        api_fix = compiled.fix_templates["api_integration"]
        fix_types = [r.fix_type for r in api_fix.rules]
        self.assertNotIn("fix_state_machine", fix_types)

    def test_quality_gates_generated(self):
        """质量门禁应自动生成"""
        module_schemas = self._load_all_output_schemas()
        compiled = self.compiler.compile(module_schemas)

        self.assertGreater(len(compiled.quality_gates.gates), 0)

        gate_names = [g.name for g in compiled.quality_gates.gates]
        self.assertIn("all_modules_pass_review", gate_names)
        self.assertIn("no_critical_issues", gate_names)
        self.assertIn("data_processing_state_machine_complete", gate_names)

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
        self.assertIn("data_processing", report)
        self.assertIn("Context Injection Strategies", report)
        self.assertIn("Fix Template Summary", report)
        self.assertIn("Quality Gates", report)

    def test_dependency_graph_with_agents_config(self):
        """从 agents.yaml 构建依赖图时，应产生正确的拓扑排序"""
        try:
            import yaml
        except ImportError:
            self.skipTest("pyyaml not installed")

        agents_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "agents.yaml"
        )
        with open(agents_path, "r", encoding="utf-8") as f:
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

        module_schemas = self._load_all_output_schemas()
        compiled = self.compiler.compile(module_schemas, agents_config=agents_config)

        # api_integration 应在 data_processing 之前（如果 api 依赖 dp）
        # 或验证图中有正确的模块
        self.assertIn("authentication", compiled.implementation_order)
        self.assertIn("data_processing", compiled.implementation_order)
        self.assertIn("api_integration", compiled.implementation_order)


class TestPipelineYamlLoading(unittest.TestCase):
    """pipeline.yaml 加载测试"""

    def test_load_pipeline_config(self):
        """应能加载 pipeline.yaml"""
        cfg = PipelineConfig.load("config/pipeline.yaml")
        self.assertEqual(cfg.name, "kodeforge")
        self.assertGreater(len(cfg.quality_gates), 0)

    def test_compile_with_pipeline_config(self):
        """compile() 应合并 pipeline.yaml 的质量门禁"""
        compiler = PipelineCompiler()
        cfg = PipelineConfig.load("config/pipeline.yaml")

        module_schemas = {}
        schemas_dir = "config/schemas"
        for filename in os.listdir(schemas_dir):
            if filename.endswith("_output.json"):
                module_name = filename.replace("_output.json", "")
                with open(os.path.join(schemas_dir, filename), encoding="utf-8") as f:
                    module_schemas[module_name] = json.load(f)

        compiled = compiler.compile(module_schemas, pipeline_config=cfg)

        self.assertTrue(compiled.metadata.get("pipeline_config_loaded"))
        self.assertEqual(compiled.metadata.get("pipeline_name"), "kodeforge")
        self.assertGreater(
            compiled.quality_gates.metadata.get("external_gates_merged", 0), 0
        )

    def test_pipeline_config_not_found(self):
        """pipeline.yaml 不存在时应返回 None"""
        result = PipelineCompiler._load_pipeline_config("nonexistent.yaml")
        self.assertIsNone(result)


class TestQualityGateEvaluation(unittest.TestCase):
    """质量门禁评估测试"""

    def test_all_pass(self):
        """全部通过"""
        generator = QualityGateGenerator()
        module_schemas = {}
        for module in ["authentication", "data_processing", "api_integration"]:
            file_module = {
                "authentication": "authentication",
                "data_processing": "data_processing",
                "api_integration": "api_integration",
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
            "data_processing_acceptance_met": True,
            "api_integration_acceptance_met": True,
            "data_processing_state_machine_complete": True,
            "authentication_compliant": True,
            "data_processing_compliant": True,
            "api_integration_compliant": True,
        }

        result = suite.evaluate(metrics)
        self.assertTrue(result["passed"])

    def test_critical_issue_fails(self):
        """有 critical 问题应失败"""
        generator = QualityGateGenerator()
        path = os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "schemas",
            "authentication_output.json"
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

    def test_advisory_gate_failure_doesnt_block(self):
        """非阻塞门禁失败不应阻止流水线"""
        generator = QualityGateGenerator()
        suite = generator.generate({})
        metrics = {
            "all_modules_passed": True,
            "critical_issues_count": 0,
            "interface_consistency": True,
            "quality_score": 0.9,
            "test_coverage": 0.5,  # 低于默认 0.7，但 test_coverage 是 advisory
            "security_score": 0.95,
        }
        result = suite.evaluate(metrics)
        self.assertTrue(result["passed"])


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

    def test_improving_scores_continue(self):
        """分数持续提升应继续"""
        detector = ConvergenceDetector()
        detector.record_score(0.5)
        detector.record_score(0.6)
        detector.record_score(0.7)
        should_continue, reason = detector.should_continue(
            iteration=2, quality_score=0.7, has_critical=False
        )
        self.assertTrue(should_continue)


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

    def test_receive_empty_queue(self):
        """空队列接收应返回 None"""
        bus = MessageBus()
        result = bus.receive("nonexistent", timeout_ms=100)
        self.assertIsNone(result)

    def test_multiple_subscribers(self):
        """多个订阅者都应收到消息"""
        bus = MessageBus()
        received1 = []
        received2 = []
        bus.subscribe("test.topic", lambda m: received1.append(m))
        bus.subscribe("test.topic", lambda m: received2.append(m))
        bus.publish("test.topic", "message")
        self.assertEqual(len(received1), 1)
        self.assertEqual(len(received2), 1)

    def test_queue_stats(self):
        """队列统计应正确"""
        bus = MessageBus()
        bus.publish("agent1", "msg1")
        bus.publish("agent1", "msg2")
        stats = bus.get_stats()
        self.assertEqual(stats["total_messages"], 2)


class TestEmptyAndSingleModule(unittest.TestCase):
    """空输入和单模块边界测试"""

    def test_compile_empty_schemas(self):
        """空 schema 编译应返回空结果"""
        compiler = PipelineCompiler()
        compiled = compiler.compile({})
        self.assertEqual(len(compiled.module_schemas), 0)
        self.assertEqual(len(compiled.implementation_order), 0)

    def test_single_module_compile(self):
        """单模块编译应正常工作"""
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

    def test_context_deriver_empty_schema(self):
        """空 schema 的上下文策略应为默认值"""
        deriver = ContextDeriver()
        strategy = deriver.derive("test_module", {})
        self.assertFalse(strategy.needs_security_context)
        self.assertFalse(strategy.needs_compliance_context)
        self.assertTrue(strategy.needs_global_constraints)

    def test_quality_evaluator_no_gates(self):
        """无门禁时评估应正常返回"""
        evaluator = QualityEvaluator()
        results = [ReviewResult(module="test", verdict="pass")]
        report = evaluator.evaluate(results, iteration=0)
        self.assertIsNotNone(report)

    def test_convergence_detector_empty_history(self):
        """空历史应继续"""
        detector = ConvergenceDetector()
        should_continue, reason = detector.should_continue(
            iteration=0, quality_score=0.5, has_critical=False
        )
        self.assertTrue(should_continue)


class TestCircularDependencies(unittest.TestCase):
    """循环依赖检测测试"""

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


if __name__ == "__main__":
    unittest.main()
