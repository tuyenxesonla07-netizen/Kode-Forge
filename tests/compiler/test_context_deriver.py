"""
tests/compiler/test_context_deriver.py

上下文注入推导器测试 — 验证 Schema → ContextStrategy 的自动推导
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tools.compiler.context_deriver import ContextDeriver, ContextStrategy


class TestContextDeriver(unittest.TestCase):
    """测试上下文注入推导器"""

    def setUp(self):
        self.deriver = ContextDeriver()
        self.schemas_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "schemas"
        )

    def _load_schema(self, filename: str) -> dict:
        path = os.path.join(self.schemas_dir, filename)
        with open(path) as f:
            return json.load(f)

    def test_auth_schema_derives_security_context(self):
        """认证模块 Schema 应推导出需要安全上下文"""
        schema = self._load_schema("auth_input.json")
        strategy = self.deriver.derive("authentication", schema)

        self.assertTrue(strategy.needs_security_context)
        self.assertTrue(strategy.needs_global_constraints)
        self.assertIn("security_requirements", strategy.injectable_fields)

    def test_order_schema_derives_dependency_interfaces(self):
        """订单模块 Schema 应推导出需要依赖接口"""
        schema = self._load_schema("order_input.json")
        strategy = self.deriver.derive("order_system", schema)

        self.assertTrue(strategy.needs_dependency_interfaces)
        self.assertTrue(strategy.needs_global_constraints)
        self.assertIn("dependency_interfaces", strategy.injectable_fields)

    def test_payment_schema_derives_compliance_context(self):
        """支付模块 Schema 应推导出需要合规上下文"""
        schema = self._load_schema("payment_input.json")
        strategy = self.deriver.derive("payment_integration", schema)

        self.assertTrue(strategy.needs_compliance_context)
        self.assertTrue(strategy.needs_global_constraints)
        self.assertIn("compliance_requirements", strategy.injectable_fields)

    def test_cart_schema_derives_business_rules(self):
        """购物车模块 Schema 应推导出需要业务规则"""
        schema = self._load_schema("cart_input.json")
        strategy = self.deriver.derive("shopping_cart", schema)

        self.assertTrue(strategy.needs_business_rules)
        self.assertIn("business_rules", strategy.injectable_fields)

    def test_notification_schema_minimal_context(self):
        """通知模块 Schema 只推导最小上下文（无安全/合规）"""
        schema = self._load_schema("notification_input.json")
        strategy = self.deriver.derive("notification_service", schema)

        self.assertTrue(strategy.needs_global_constraints)
        self.assertFalse(strategy.needs_security_context)
        self.assertFalse(strategy.needs_compliance_context)
        self.assertFalse(strategy.needs_business_rules)

    def test_product_schema_derives_search_requirements(self):
        """商品模块 Schema 应推导出需要搜索需求"""
        schema = self._load_schema("product_input.json")
        strategy = self.deriver.derive("product_catalog", schema)

        self.assertTrue(strategy.needs_search_requirements)
        self.assertIn("search_requirements", strategy.injectable_fields)

    def test_report_schema_no_extra_context(self):
        """报表模块 Schema 不推导额外上下文"""
        schema = self._load_schema("report_input.json")
        strategy = self.deriver.derive("data_reporting", schema)

        self.assertTrue(strategy.needs_global_constraints)
        self.assertFalse(strategy.needs_security_context)
        self.assertFalse(strategy.needs_compliance_context)

    def test_derive_all_returns_all_modules(self):
        """批量推导应返回所有模块的策略"""
        schemas = {}
        for filename in os.listdir(self.schemas_dir):
            if filename.endswith("_input.json"):
                module = filename.replace("_input.json", "")
                schemas[module] = self._load_schema(filename)

        strategies = self.deriver.derive_all(schemas)

        self.assertEqual(len(strategies), len(schemas))
        for module in schemas:
            self.assertIn(module, strategies)
            self.assertEqual(strategies[module].module_name, module)

    def test_explain_output_is_readable(self):
        """推导说明应生成人类可读的文本"""
        schema = self._load_schema("auth_input.json")
        strategy = self.deriver.derive("authentication", schema)
        explanation = self.deriver.explain(strategy)

        self.assertIn("authentication", explanation)
        self.assertIn("安全上下文", explanation)
        self.assertIn("全局约束", explanation)


class TestContextStrategyIsolation(unittest.TestCase):
    """测试上下文隔离：不同模块推导出的策略互不干扰"""

    def setUp(self):
        self.deriver = ContextDeriver()
        self.schemas_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "schemas"
        )

    def _load_schema(self, filename: str) -> dict:
        path = os.path.join(self.schemas_dir, filename)
        with open(path) as f:
            return json.load(f)

    def test_auth_has_security_but_notification_doesnt(self):
        """认证有安全上下文，通知没有"""
        auth_schema = self._load_schema("auth_input.json")
        notif_schema = self._load_schema("notification_input.json")

        auth_strategy = self.deriver.derive("authentication", auth_schema)
        notif_strategy = self.deriver.derive("notification_service", notif_schema)

        self.assertTrue(auth_strategy.needs_security_context)
        self.assertFalse(notif_strategy.needs_security_context)

    def test_payment_has_compliance_but_cart_doesnt(self):
        """支付有合规上下文，购物车没有"""
        pay_schema = self._load_schema("payment_input.json")
        cart_schema = self._load_schema("cart_input.json")

        pay_strategy = self.deriver.derive("payment_integration", pay_schema)
        cart_strategy = self.deriver.derive("shopping_cart", cart_schema)

        self.assertTrue(pay_strategy.needs_compliance_context)
        self.assertFalse(cart_strategy.needs_compliance_context)


if __name__ == "__main__":
    unittest.main()
