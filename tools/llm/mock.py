# tools/llm/mock.py

"""
Mock LLM Provider — 无需 API key，返回预设结果

用于开发测试，无需真实 LLM 调用。
根据 prompt 内容智能匹配预设响应。
"""

import json
from typing import Dict, List

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
    # 数据处理模块
    "data_processing": {
        "analysis": {
            "module_name": "data_processing",
            "components": [
                {"name": "DataPipeline", "type": "service", "description": "数据处理流水线"},
                {"name": "TransformService", "type": "service", "description": "数据转换服务"},
                {"name": "DataModel", "type": "model", "description": "数据模型"},
                {"name": "DataController", "type": "route", "description": "数据处理路由"},
            ],
            "interfaces": [
                {"name": "transform", "method": "POST", "path": "/api/data/transform", "description": "数据转换"},
                {"name": "validate", "method": "POST", "path": "/api/data/validate", "description": "数据校验"},
                {"name": "get_result", "method": "GET", "path": "/api/data/result/{id}", "description": "获取结果"},
            ],
            "acceptance_criteria": [
                "数据可正确转换",
                "处理结果可查询",
                "转换失败正确回滚",
            ],
            "state_machine": {
                "states": ["pending", "processing", "completed", "failed"],
                "transitions": [
                    {"from": "pending", "to": "processing", "trigger": "start"},
                    {"from": "processing", "to": "completed", "trigger": "finish"},
                    {"from": "processing", "to": "failed", "trigger": "error"},
                ],
            },
            "confidence": 0.90,
            "reasoning": "数据处理模块需要状态机管理流水线状态",
        },
        "review": {
            "verdict": "pass",
            "issues": [],
            "metrics": {"coverage": 0.85, "complexity": 12, "security_score": 0.88},
        },
    },
    # API 集成模块
    "api_integration": {
        "analysis": {
            "module_name": "api_integration",
            "components": [
                {"name": "APIClient", "type": "service", "description": "API 客户端服务"},
                {"name": "AuthMiddleware", "type": "middleware", "description": "认证中间件"},
                {"name": "RateLimitMiddleware", "type": "middleware", "description": "限流中间件"},
                {"name": "ResponseModel", "type": "model", "description": "响应数据模型"},
            ],
            "interfaces": [
                {"name": "call_external_api", "method": "POST", "path": "/api/external", "description": "调用外部 API"},
                {"name": "get_status", "method": "GET", "path": "/api/external/status/{id}", "description": "查询状态"},
                {"name": "retry", "method": "POST", "path": "/api/external/retry/{id}", "description": "重试"},
            ],
            "acceptance_criteria": [
                "外部 API 调用幂等处理",
                "失败自动重试不超过 3 次",
                "限流时正确排队",
            ],
            "confidence": 0.87,
            "reasoning": "API 集成模块需要幂等性和错误处理",
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
    if any(k in prompt_lower for k in ["data", "数据", "处理", "transform", "pipeline"]):
        return "data_processing"
    if any(k in prompt_lower for k in ["api", "接口", "集成", "integration", "external"]):
        return "api_integration"
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

    def __init__(self, custom_responses: Dict = None, default_confidence: float = 0.85) -> None:
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

    async def acomplete(
        self,
        prompt: str,
        system_prompt: str = "",
        output_format: str = "text",
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """异步返回预设响应（直接委托给 complete）"""
        return self.complete(prompt, system_prompt, output_format, max_tokens, temperature)

    def get_name(self) -> str:
        return "mock"

    def get_call_history(self) -> List[Dict]:
        """获取调用历史（用于测试验证）"""
        return list(self._call_history)

    def clear_history(self) -> None:
        """清空调用历史"""
        self._call_history.clear()
