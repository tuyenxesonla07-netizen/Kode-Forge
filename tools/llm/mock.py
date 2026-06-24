# tools/llm/mock.py

"""
Mock LLM Provider — 无需 API key，返回预设结果

用于开发测试，无需真实 LLM 调用。
根据 prompt 内容智能匹配预设响应。
"""

import json
import re
from typing import Any, Dict, List, Optional

from tools.llm.base import LLMProvider, LLMResponse


# 预设响应模板
MOCK_RESPONSES = {
    # 认证模块
    "auth": {
        "analysis": {
            "module_name": "authentication",
            "components": [
                {"name": "AuthService", "type": "service", "description": "认证服务，处理登录注册"},
                {"name": "TokenManager", "type": "service", "description": "JWT Token 管理"},
                {"name": "UserModel", "type": "model", "description": "用户数据模型"},
                {"name": "AuthController", "type": "route", "description": "认证路由处理器"},
                {"name": "AuthMiddleware", "type": "middleware", "description": "认证中间件"},
            ],
            "interfaces": [
                {"name": "login", "method": "POST", "path": "/api/auth/login", "description": "用户登录"},
                {"name": "register", "method": "POST", "path": "/api/auth/register", "description": "用户注册"},
                {"name": "refresh", "method": "POST", "path": "/api/auth/refresh", "description": "刷新 Token"},
                {"name": "logout", "method": "POST", "path": "/api/auth/logout", "description": "用户登出"},
            ],
            "acceptance_criteria": [
                "用户可使用邮箱密码登录",
                "Token 过期自动刷新",
                "登出后 token 失效",
                "密码使用 bcrypt 加密存储",
            ],
            "confidence": 0.92,
            "reasoning": "基于 JWT 的认证方案，RS256 算法，24h 有效期",
        },
        "review": {
            "verdict": "pass",
            "issues": [],
            "metrics": {"coverage": 0.88, "complexity": 8, "security_score": 0.95},
        },
    },
    # 订单模块
    "order": {
        "analysis": {
            "module_name": "order_system",
            "components": [
                {"name": "OrderService", "type": "service", "description": "订单服务"},
                {"name": "OrderModel", "type": "model", "description": "订单数据模型"},
                {"name": "OrderStateMachine", "type": "util", "description": "订单状态机"},
                {"name": "OrderController", "type": "route", "description": "订单路由"},
            ],
            "interfaces": [
                {"name": "create_order", "method": "POST", "path": "/api/orders", "description": "创建订单"},
                {"name": "get_order", "method": "GET", "path": "/api/orders/{id}", "description": "查询订单"},
                {"name": "cancel_order", "method": "POST", "path": "/api/orders/{id}/cancel", "description": "取消订单"},
            ],
            "acceptance_criteria": [
                "用户可创建订单",
                "订单状态正确流转 pending→confirmed→shipped→delivered",
                "取消订单释放库存",
            ],
            "state_machine": {
                "states": ["pending", "confirmed", "shipped", "delivered", "cancelled"],
                "transitions": [
                    {"from": "pending", "to": "confirmed", "trigger": "confirm"},
                    {"from": "confirmed", "to": "shipped", "trigger": "ship"},
                    {"from": "shipped", "to": "delivered", "trigger": "deliver"},
                    {"from": "pending", "to": "cancelled", "trigger": "cancel"},
                ],
            },
            "confidence": 0.90,
            "reasoning": "订单系统需要状态机管理，确保数据一致性",
        },
        "review": {
            "verdict": "pass",
            "issues": [],
            "metrics": {"coverage": 0.85, "complexity": 12, "security_score": 0.88},
        },
    },
    # 支付模块
    "payment": {
        "analysis": {
            "module_name": "payment_integration",
            "components": [
                {"name": "PaymentService", "type": "service", "description": "支付服务"},
                {"name": "PaymentGateway", "type": "middleware", "description": "支付网关中间件"},
                {"name": "PaymentModel", "type": "model", "description": "支付数据模型"},
                {"name": "RefundService", "type": "service", "description": "退款服务"},
            ],
            "interfaces": [
                {"name": "create_payment", "method": "POST", "path": "/api/payments", "description": "创建支付"},
                {"name": "get_payment", "method": "GET", "path": "/api/payments/{id}", "description": "查询支付"},
                {"name": "refund", "method": "POST", "path": "/api/payments/{id}/refund", "description": "退款"},
            ],
            "acceptance_criteria": [
                "支付请求幂等处理",
                "退款金额不超过原支付金额",
                "支付失败正确回滚",
            ],
            "confidence": 0.87,
            "reasoning": "支付模块需要幂等性和事务安全",
        },
        "review": {
            "verdict": "pass",
            "issues": [],
            "metrics": {"coverage": 0.82, "complexity": 10, "security_score": 0.92},
        },
    },
    # 默认响应
    "default": {
        "analysis": {
            "module_name": "unknown",
            "components": [
                {"name": "MainService", "type": "service", "description": "主要服务"},
                {"name": "MainModel", "type": "model", "description": "数据模型"},
                {"name": "MainController", "type": "route", "description": "路由控制器"},
            ],
            "interfaces": [
                {"name": "create", "method": "POST", "path": "/api/items", "description": "创建"},
                {"name": "get", "method": "GET", "path": "/api/items/{id}", "description": "查询"},
            ],
            "acceptance_criteria": ["可创建资源", "可查询资源"],
            "confidence": 0.80,
            "reasoning": "基于 Schema 的默认分析",
        },
        "review": {
            "verdict": "pass",
            "issues": [],
            "metrics": {"coverage": 0.75, "complexity": 6, "security_score": 0.85},
        },
    },
}


def _detect_module(prompt: str) -> str:
    """从 prompt 检测模块类型"""
    prompt_lower = prompt.lower()
    if any(k in prompt_lower for k in ["auth", "登录", "注册", "认证", "token", "jwt"]):
        return "auth"
    if any(k in prompt_lower for k in ["order", "订单", "下单", "购物车"]):
        return "order"
    if any(k in prompt_lower for k in ["payment", "支付", "付款", "退款"]):
        return "payment"
    return "default"


def _detect_task(prompt: str) -> str:
    """从 prompt 检测任务类型: analysis 或 review"""
    if any(k in prompt.lower() for k in ["review", "审查", "检查", "审核", "code_snippet"]):
        return "review"
    return "analysis"


class MockLLMProvider(LLMProvider):
    """
    Mock LLM Provider — 无需 API key

    根据 prompt 内容智能匹配预设响应。
    支持自定义响应注入。
    """

    def __init__(self, custom_responses: Dict = None, default_confidence: float = 0.85):
        self.custom_responses = custom_responses or {}
        self.default_confidence = default_confidence
        self._call_history: List[Dict] = []

    def complete(
        self,
        prompt: str,
        system_prompt: str = "",
        output_format: str = "text",
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """返回预设响应"""
        module = _detect_module(prompt)
        task = _detect_task(prompt)

        # 优先使用自定义响应
        if module in self.custom_responses:
            data = self.custom_responses[module]
        else:
            data = MOCK_RESPONSES.get(module, MOCK_RESPONSES["default"])

        response_data = data.get(task, data["analysis"])

        # 构建 JSON 文本
        content = json.dumps(response_data, ensure_ascii=False, indent=2)

        self._call_history.append({
            "module": module,
            "task": task,
            "prompt_length": len(prompt),
        })

        return LLMResponse(
            content=content,
            parsed=response_data,
            tokens_used=len(content) // 4,  # 粗略估算
            model="mock-claude-sonnet-4-5",
            success=True,
        )

    def get_name(self) -> str:
        return "mock"

    def get_call_history(self) -> List[Dict]:
        """获取调用历史（用于测试验证）"""
        return list(self._call_history)

    def clear_history(self):
        """清空调用历史"""
        self._call_history.clear()
