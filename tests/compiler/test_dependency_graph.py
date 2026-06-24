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
        """简单依赖链: auth → order → payment"""
        self.graph.add_module("auth", [])
        self.graph.add_module("order", ["auth"])
        self.graph.add_module("payment", ["order"])

        result = self.graph.topological_sort()

        self.assertEqual(result, ["auth", "order", "payment"])

    def test_topological_sort_parallel(self):
        """并行模块: auth 无依赖, product 和 cart 都依赖 auth"""
        self.graph.add_module("auth", [])
        self.graph.add_module("product", ["auth"])
        self.graph.add_module("cart", ["auth"])
        self.graph.add_module("order", ["auth", "cart"])

        result = self.graph.topological_sort()

        # auth 必须在最前
        self.assertEqual(result[0], "auth")
        # order 必须在 cart 之后
        self.assertLess(result.index("cart"), result.index("order"))
        # product 和 cart 的顺序不确定，但都在 auth 之后
        self.assertLess(result.index("auth"), result.index("product"))
        self.assertLess(result.index("auth"), result.index("cart"))

    def test_topological_sort_ecommerce_7_modules(self):
        """完整的 7 模块电商依赖图"""
        self.graph.add_module("authentication", [])
        self.graph.add_module("product_catalog", ["authentication"])
        self.graph.add_module("shopping_cart", ["authentication"])
        self.graph.add_module("order_system", ["authentication", "shopping_cart"])
        self.graph.add_module("payment_integration", ["authentication", "order_system"])
        self.graph.add_module("notification_service", ["authentication"])
        self.graph.add_module("data_reporting", ["authentication", "order_system"])

        result = self.graph.topological_sort()

        self.assertEqual(len(result), 7)
        self.assertEqual(result[0], "authentication")
        # order 在 cart 之后
        self.assertLess(result.index("shopping_cart"), result.index("order_system"))
        # payment 在 order 之后
        self.assertLess(result.index("order_system"), result.index("payment_integration"))
        # report 在 order 之后
        self.assertLess(result.index("order_system"), result.index("data_reporting"))

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
        self.graph.add_module("order", ["auth"])

        self.assertFalse(self.graph.has_cycle())

    def test_has_cycle_true(self):
        """有环图 has_cycle 返回 True"""
        self.graph.add_module("a", ["b"])
        self.graph.add_module("b", ["a"])

        self.assertTrue(self.graph.has_cycle())

    def test_get_all_dependencies(self):
        """传递依赖查询"""
        self.graph.add_module("auth", [])
        self.graph.add_module("cart", ["auth"])
        self.graph.add_module("order", ["auth", "cart"])
        self.graph.add_module("payment", ["auth", "order"])

        all_deps = self.graph.get_all_dependencies("payment")
        self.assertEqual(all_deps, {"auth", "cart", "order"})

    def test_get_dependents(self):
        """反向依赖查询"""
        self.graph.add_module("auth", [])
        self.graph.add_module("cart", ["auth"])
        self.graph.add_module("order", ["auth", "cart"])

        dependents = self.graph.get_dependents("auth")
        self.assertIn("cart", dependents)
        self.assertIn("order", dependents)

    def test_parallel_groups(self):
        """并行组识别"""
        self.graph.add_module("auth", [])
        self.graph.add_module("product", ["auth"])
        self.graph.add_module("cart", ["auth"])
        self.graph.add_module("order", ["auth", "cart"])

        groups = self.graph.get_parallel_groups()

        # 第一组: [auth]
        self.assertEqual(groups[0], ["auth"])
        # 第二组: [product, cart]（可并行）
        self.assertEqual(set(groups[1]), {"product", "cart"})
        # 第三组: [order]
        self.assertEqual(groups[2], ["order"])


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
                "expert_order": {
                    "role": "expert",
                    "module": "order_system",
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
        self.assertIn("order_system", graph.nodes)
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
                "expert_order": {
                    "role": "expert",
                    "module": "order_system",
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
                "expert_order": {
                    "role": "expert",
                    "module": "order_system",
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
