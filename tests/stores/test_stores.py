"""
tests/stores/test_stores.py

三大 Store 组件测试
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tools.stores.requirement_store import RequirementStore, ModuleRequirement
from tools.stores.interface_store import InterfaceStore, InterfaceDef
from tools.stores.spec_store import SpecStore, ModuleSpec, ComponentDef


class TestRequirementStore(unittest.TestCase):
    """测试需求上下文存储"""

    def setUp(self):
        self.store = RequirementStore()

    def test_put_and_get(self):
        """存储和获取"""
        req = ModuleRequirement(
            module_name="authentication",
            description="JWT 认证的登录注册功能",
            constraints=["RS256", "24h-token"],
            priority=1,
        )
        self.store.put("authentication", req)

        result = self.store.get("authentication")
        self.assertIsNotNone(result)
        self.assertEqual(result.module_name, "authentication")

    def test_get_for_injection_excludes_others(self):
        """注入格式化应只包含该模块的信息"""
        self.store.put("authentication", ModuleRequirement(
            module_name="authentication",
            description="JWT 认证",
            constraints=["RS256"],
            security_requirements=["密码加密存储"],
        ))
        self.store.put("order", ModuleRequirement(
            module_name="order",
            description="订单系统",
            constraints=["事务一致性"],
        ))

        auth_injection = self.store.get_for_injection("authentication")
        order_injection = self.store.get_for_injection("order")

        # 认证注入包含安全要求，不包含订单信息
        self.assertIn("JWT 认证", auth_injection)
        self.assertIn("密码加密存储", auth_injection)
        self.assertNotIn("订单系统", auth_injection)

        # 订单注入不包含认证信息
        self.assertIn("订单系统", order_injection)
        self.assertNotIn("JWT 认证", order_injection)

    def test_get_priority_order(self):
        """按优先级排序"""
        self.store.put("payment", ModuleRequirement(
            module_name="payment", description="支付", priority=4
        ))
        self.store.put("auth", ModuleRequirement(
            module_name="auth", description="认证", priority=1
        ))
        self.store.put("order", ModuleRequirement(
            module_name="order", description="订单", priority=3
        ))

        order = self.store.get_priority_order()
        self.assertEqual(order, ["auth", "order", "payment"])


class TestInterfaceStore(unittest.TestCase):
    """测试接口定义存储"""

    def setUp(self):
        self.store = InterfaceStore()

    def test_register_and_get_for_injection(self):
        """注册模块接口并获取注入内容"""
        interfaces = [
            InterfaceDef(
                name="login",
                method="POST",
                path="/api/auth/login",
                input_schema={"email": "string", "password": "string"},
                output_schema={"access_token": "string"},
                description="用户登录",
            ),
            InterfaceDef(
                name="register",
                method="POST",
                path="/api/auth/register",
                input_schema={"email": "string", "password": "string"},
                output_schema={"user_id": "string"},
                description="用户注册",
            ),
        ]

        self.store.register_module("authentication", interfaces)

        # 获取注入内容
        injection = self.store.get_for_injection("authentication")
        self.assertIn("login", injection)
        self.assertIn("register", injection)
        self.assertIn("POST", injection)

        # 不包含实现代码
        self.assertNotIn("def login", injection)
        self.assertNotIn("implementation", injection)

    def test_get_sistent(self):
        """获取不存在的模块返回空"""
        result = self.store.get_for_injection("nonexistent")
        self.assertEqual(result, "")

    def test_cross_module_interfaces(self):
        """获取跨模块接口"""
        self.store.register_module("auth", [
            InterfaceDef(name="get_user", method="GET", path="/api/users/{id}"),
        ])
        self.store.register_module("order", [
            InterfaceDef(name="create_order", method="POST", path="/api/orders"),
        ])

        cross = self.store.get_cross_module_interfaces(["auth", "order"])
        self.assertIn("auth", cross)
        self.assertIn("order", cross)


class TestSpecStore(unittest.TestCase):
    """测试模块规格存储"""

    def setUp(self):
        self.store = SpecStore()

    def test_put_and_get(self):
        """存储和获取"""
        spec = ModuleSpec(
            module_name="authentication",
            components=[
                ComponentDef(name="AuthService", type="service", description="认证服务"),
            ],
            acceptance_criteria=["用户可登录", "token 过期自动刷新"],
            confidence=0.92,
        )
        self.store.put("authentication", spec)

        result = self.store.get("authentication")
        self.assertIsNotNone(result)
        self.assertEqual(result.confidence, 0.92)

    def test_get_ordered(self):
        """按实现顺序获取"""
        self.store.put("auth", ModuleSpec(module_name="auth", confidence=0.9))
        self.store.put("order", ModuleSpec(module_name="order", confidence=0.85))
        self.store.put("payment", ModuleSpec(module_name="payment", confidence=0.88))

        ordered = self.store.get_ordered(["auth", "order", "payment"])
        self.assertEqual(len(ordered), 3)
        self.assertEqual(ordered[0].module_name, "auth")

    def test_get_overall_confidence(self):
        """平均置信度"""
        self.store.put("auth", ModuleSpec(module_name="auth", confidence=0.9))
        self.store.put("order", ModuleSpec(module_name="order", confidence=0.7))

        avg = self.store.get_overall_confidence()
        self.assertAlmostEqual(avg, 0.8)

    def test_get_modules_with_state_machine(self):
        """获取有状态机的模块"""
        self.store.put("order", ModuleSpec(
            module_name="order",
            state_machine={"states": ["pending", "confirmed"], "transitions": []},
        ))
        self.store.put("auth", ModuleSpec(module_name="auth"))

        modules = self.store.get_modules_with_state_machine()
        self.assertEqual(modules, ["order"])


if __name__ == "__main__":
    unittest.main()
