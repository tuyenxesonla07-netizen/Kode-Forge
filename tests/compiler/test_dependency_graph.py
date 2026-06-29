"""
tests/compiler/test_dependency_graph.py

依赖图构建器测试 — 验证拓扑排序和环检测
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tools.compiler.dependency_graph import DependencyGraph, DependencyGraphBuilder


class TestDependencyGraph(unittest.TestCase):
    """测试依赖图"""

    def setUp(self):
        self.graph = DependencyGraph()

    def test_topological_sort_simple(self):
        """简单依赖链: authentication → data_processing → api_integration"""
        self.graph.add_module("authentication", [])
        self.graph.add_module("data_processing", ["authentication"])
        self.graph.add_module("api_integration", ["data_processing"])

        result = self.graph.topological_sort()

        self.assertEqual(result, ["authentication", "data_processing", "api_integration"])

    def test_topological_sort_parallel(self):
        """并行模块: authentication 无依赖, data_processing 和 api_integration 都依赖 authentication"""
        self.graph.add_module("authentication", [])
        self.graph.add_module("data_processing", ["authentication"])
        self.graph.add_module("api_integration", ["authentication"])

        result = self.graph.topological_sort()

        # authentication 必须在最前
        self.assertEqual(result[0], "authentication")
        # data_processing 和 api_integration 的顺序不确定，但都在 authentication 之后
        self.assertLess(result.index("authentication"), result.index("data_processing"))
        self.assertLess(result.index("authentication"), result.index("api_integration"))

    def test_topological_sort_three_modules(self):
        """完整的 3 模块依赖图: authentication → data_processing → api_integration"""
        self.graph.add_module("authentication", [])
        self.graph.add_module("data_processing", ["authentication"])
        self.graph.add_module("api_integration", ["authentication", "data_processing"])

        result = self.graph.topological_sort()

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], "authentication")
        # data_processing 在 api_integration 之前
        self.assertLess(result.index("data_processing"), result.index("api_integration"))

    def test_cycle_detection(self):
        """循环依赖应抛出 ValueError"""
        self.graph.add_module("a", ["b"])
        self.graph.add_module("b", ["c"])
        self.graph.add_module("c", ["a"])

        with self.assertRaises(ValueError) as ctx:
            self.graph.topological_sort()

        self.assertIn("循环依赖", str(ctx.exception))

    def test_has_cycle_false(self):
        """无环图 has_cycle 返回 False"""
        self.graph.add_module("auth", [])
        self.graph.add_module("api_integration", ["auth"])

        self.assertFalse(self.graph.has_cycle())

    def test_has_cycle_true(self):
        """有环图 has_cycle 返回 True"""
        self.graph.add_module("a", ["b"])
        self.graph.add_module("b", ["a"])

        self.assertTrue(self.graph.has_cycle())

    def test_get_all_dependencies(self):
        """传递依赖查询"""
        self.graph.add_module("authentication", [])
        self.graph.add_module("api_integration", ["authentication"])
        self.graph.add_module("data_processing", ["authentication", "api_integration"])

        all_deps = self.graph.get_all_dependencies("data_processing")
        self.assertEqual(all_deps, {"authentication", "api_integration"})

    def test_get_dependents(self):
        """反向依赖查询"""
        self.graph.add_module("authentication", [])
        self.graph.add_module("api_integration", ["authentication"])
        self.graph.add_module("data_processing", ["authentication", "api_integration"])

        dependents = self.graph.get_dependents("authentication")
        self.assertIn("api_integration", dependents)
        self.assertIn("data_processing", dependents)

    def test_parallel_groups(self):
        """并行组识别"""
        self.graph.add_module("authentication", [])
        self.graph.add_module("data_processing", ["authentication"])
        self.graph.add_module("api_integration", ["authentication"])

        groups = self.graph.get_parallel_groups()

        # 第一组: [authentication]
        self.assertEqual(groups[0], ["authentication"])
        # 第二组: [data_processing, api_integration]（可并行）
        self.assertEqual(set(groups[1]), {"data_processing", "api_integration"})


class TestDependencyGraphBuilder(unittest.TestCase):
    """测试从 agents.yaml 构建依赖图"""

    def test_build_from_config(self):
        """从配置构建依赖图"""
        agents_config = {
            "agents": {
                "expert_auth": {
                    "role": "expert",
                    "module": "authentication",
                    "dependencies": [],
                },
                "expert_data_processing": {
                    "role": "expert",
                    "module": "data_processing",
                    "dependencies": ["authentication"],
                },
                "expert_supervisor": {
                    "role": "supervisor",
                    "module": "orchestration",
                },
            }
        }

        builder = DependencyGraphBuilder(agents_config)
        graph = builder.build()

        self.assertIn("authentication", graph.nodes)
        self.assertIn("data_processing", graph.nodes)
        # supervisor 不应被包含（role != expert）
        self.assertNotIn("orchestration", graph.nodes)

    def test_validate_no_errors(self):
        """验证无错误的配置"""
        agents_config = {
            "agents": {
                "expert_auth": {
                    "role": "expert",
                    "module": "authentication",
                    "dependencies": [],
                },
                "expert_data_processing": {
                    "role": "expert",
                    "module": "data_processing",
                    "dependencies": ["authentication"],
                },
            }
        }

        builder = DependencyGraphBuilder(agents_config)
        is_valid, errors = builder.validate()

        self.assertTrue(is_valid)
        self.assertEqual(errors, [])

    def test_validate_missing_dependency(self):
        """验证缺失的依赖"""
        agents_config = {
            "agents": {
                "expert_data_processing": {
                    "role": "expert",
                    "module": "data_processing",
                    "dependencies": ["nonexistent_module"],
                },
            }
        }

        builder = DependencyGraphBuilder(agents_config)
        is_valid, errors = builder.validate()

        self.assertFalse(is_valid)
        self.assertTrue(any("nonexistent_module" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
