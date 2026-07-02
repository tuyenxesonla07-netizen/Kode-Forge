# agents/supervisor/router.py

"""
SupervisorRouter — 意图路由器：将用户消息路由到对应的处理流水线。

借鉴 codex 的 supervisor_node + customer-service-course 的 ROUTES 字典。
包装现有 CodexSupervisor，不修改它（保护已有 1402 个测试）。

用法:
    from agents.supervisor.router import SupervisorRouter

    router = SupervisorRouter(llm_provider=mock_provider)
    state = await router.route("帮我构建用户登录模块")
    print(state.intent)   # "code_generation"
    print(state.reply)    # 生成的回复
"""

from __future__ import annotations

import logging
from typing import Any

from agents.runtime.state import AgentState, StopReason, create_agent_state

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SupervisorRouter
# ---------------------------------------------------------------------------

class SupervisorRouter:
    """意图路由器：将用户消息路由到对应的处理流水线。"""

    # 支持的意图集合
    INTENTS = {
        "code_generation": "编译流水线 + 代码生成",
        "code_fix": "定位问题 → 修复 → 重新生成",
        "quality_check": "运行质量门禁",
        "knowledge_query": "RAG 检索",
        "approval_action": "审批操作",
    }

    def __init__(
        self,
        llm_provider: Any = None,
        intent_classifier: Any = None,
        approval_handler: Any = None,
        skill_registry: Any = None,
        tool_registry: Any = None,
    ) -> None:
        self._llm = llm_provider
        self._intent_classifier = intent_classifier
        self._approval_handler = approval_handler
        self._skill_registry = skill_registry
        self._tool_registry = tool_registry

    async def route(self, message: str, state: AgentState | None = None) -> AgentState:
        """主入口：意图分类 → 路由到对应 handler。

        Args:
            message: 用户消息
            state: 可选的已有 AgentState（用于多轮对话）

        Returns:
            处理后的 AgentState
        """
        if state is None:
            state = create_agent_state(message)
        else:
            state.add_message("user", message)
            state.message = message

        # 1. 意图分类
        intent = self._classify_intent(message)
        state.intent = intent
        state.add_trace("intent_classified", {"intent": intent})

        # 2. 路由到对应 handler
        handler_name = f"_handle_{intent}"
        handler = getattr(self, handler_name, self._handle_unknown)

        state.add_trace("routing", {"handler": handler_name})
        result_state = await handler(message, state)

        # 3. 添加 assistant 回复到 history
        if result_state.reply:
            result_state.add_message("assistant", result_state.reply)

        return result_state

    def _classify_intent(self, message: str) -> str:
        """对消息进行意图分类。

        优先使用注入的 IntentClassifier，否则使用基于规则的简单分类。
        """
        if self._intent_classifier is not None:
            result = self._intent_classifier(message)
            if hasattr(result, "primary_intent"):
                return result.primary_intent
            if isinstance(result, str):
                return result

        # 基于关键词的简单分类
        return self._rule_based_classify(message)

    def _rule_based_classify(self, message: str) -> str:
        """基于关键词的规则分类（fallback）。"""
        msg_lower = message.lower()

        # 审批相关
        approval_keywords = ["审批", "批准", "approve", "reject", "通过", "拒绝"]
        if any(kw in msg_lower for kw in approval_keywords):
            return "approval_action"

        # 质量检查
        quality_keywords = ["质量", "检查", "审查", "review", "check", "test", "门禁"]
        if any(kw in msg_lower for kw in quality_keywords):
            return "quality_check"

        # 代码修复
        fix_keywords = ["修复", "fix", "bug", "错误", "error", "问题", "issue", "broken"]
        if any(kw in msg_lower for kw in fix_keywords):
            return "code_fix"

        # 知识查询
        knowledge_keywords = ["什么", "怎么", "如何", "什么是", "how", "what", "why",
                              "为什么", "文档", "doc", "帮助", "help", "查询", "search"]
        if any(kw in msg_lower for kw in knowledge_keywords):
            return "knowledge_query"

        # 代码生成（默认）
        code_keywords = ["生成", "创建", "编写", "实现", "build", "create",
                         "generate", "implement", "编写代码", "开发", "写"]
        if any(kw in msg_lower for kw in code_keywords):
            return "code_generation"

        return "knowledge_query"  # 默认 fallback

    # -------------------------------------------------------------------
    # Intent Handlers
    # -------------------------------------------------------------------

    async def _handle_code_generation(self, message: str, state: AgentState) -> AgentState:
        """处理 code_generation 意图。"""
        state.add_trace("handling_code_generation", {})
        return await self._run_react_loop(message, state)

    async def _handle_code_fix(self, message: str, state: AgentState) -> AgentState:
        """处理 code_fix 意图。"""
        state.add_trace("handling_code_fix", {})
        return await self._run_react_loop(message, state)

    async def _handle_quality_check(self, message: str, state: AgentState) -> AgentState:
        """处理 quality_check 意图。"""
        state.add_trace("handling_quality_check", {})
        return await self._run_react_loop(message, state)

    async def _handle_knowledge_query(self, message: str, state: AgentState) -> AgentState:
        """处理 knowledge_query 意图。"""
        state.add_trace("handling_knowledge_query", {})
        return await self._run_react_loop(message, state)

    async def _run_react_loop(self, message: str, state: AgentState) -> AgentState:
        """通过 ReActLoop 处理请求（所有 intent 的统一执行路径）。"""
        if self._llm is not None:
            try:
                from agents.runtime.loop import ReActLoop, ReActLoopConfig
                loop = ReActLoop(
                    llm_provider=self._llm,
                    tool_registry=self._tool_registry,
                    config=ReActLoopConfig(max_steps=state.max_steps),
                )
                return await loop.run(state)
            except Exception as e:
                logger.error("[SupervisorRouter] ReActLoop error: %s", e)
                state.last_error = str(e)
                state.stop_reason = StopReason.ERROR
                return state

        # 无 LLM 时返回 intent 对应的 stub 回复
        _replies = {
            "code_generation": f"收到代码生成请求：{message}。正在编译流水线...",
            "code_fix": f"收到代码修复请求：{message}。正在定位问题并生成修复...",
            "quality_check": "正在运行质量门禁检查...",
            "knowledge_query": f"正在检索知识库以回答：{message}",
        }
        state.reply = _replies.get(state.intent, f"收到 {state.intent} 请求：{message}")
        state.stop_reason = StopReason.ANSWERED
        return state

    async def _handle_approval_action(self, message: str, state: AgentState) -> AgentState:
        """处理 approval_action 意图。"""
        state.add_trace("handling_approval_action", {})

        if self._approval_handler is not None:
            result = self._approval_handler.request_approval(
                tool_name="manual_action",
                args={"message": message},
                risk_level="medium",
                context={},
            )
            state.approval_result = {
                "approved": result.approved,
                "comment": result.comment,
            }
            state.reply = f"审批结果：{'已通过' if result.approved else '待审批'}"
        else:
            state.reply = f"收到审批请求：{message}"
            state.stop_reason = StopReason.WAITING_HUMAN

        return state

    async def _handle_unknown(self, message: str, state: AgentState) -> AgentState:
        """未知意图 fallback。"""
        state.add_trace("unknown_intent", {"message": message})
        state.reply = f"我无法理解您的请求：{message}。请尝试更具体的描述。"
        state.stop_reason = StopReason.NEED_MORE_INFO
        return state
