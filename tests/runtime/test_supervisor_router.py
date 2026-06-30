# tests/runtime/test_supervisor_router.py

"""
tests/runtime/test_supervisor_router.py — SupervisorRouter 单元测试。

覆盖：初始化、意图分类、各 handler 路由、fallback、状态字段设置。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest
from agents.supervisor.router import SupervisorRouter
from agents.runtime.state import AgentState, StopReason, create_agent_state


# ---------------------------------------------------------------------------
# Mock LLM Provider
# ---------------------------------------------------------------------------

@dataclass
class MockLLMResponse:
    content: str
    success: bool = True


class MockLLMProvider:
    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = responses or ["Action: respond\nInput: done"]
        self._call_count = 0

    def complete(self, prompt: str, system_prompt: str = "",
                 output_format: str = "text", **kwargs: Any) -> MockLLMResponse:
        if self._call_count < len(self._responses):
            content = self._responses[self._call_count]
        else:
            content = "Action: respond\nInput: done"
        self._call_count += 1
        return MockLLMResponse(content=content)


# ---------------------------------------------------------------------------
# Tests: Initialization
# ---------------------------------------------------------------------------

class TestRouterInit:
    def test_router_init_defaults(self):
        """默认初始化。"""
        router = SupervisorRouter()
        assert router._llm is None
        assert router._intent_classifier is None

    def test_router_init_with_llm(self):
        """带 LLM provider 初始化。"""
        llm = MockLLMProvider()
        router = SupervisorRouter(llm_provider=llm)
        assert router._llm is llm


# ---------------------------------------------------------------------------
# Tests: Intent Classification
# ---------------------------------------------------------------------------

class TestIntentClassification:
    def test_classify_code_generation(self):
        """code_generation 意图分类。"""
        router = SupervisorRouter()

        code_msgs = [
            "帮我生成一个用户登录模块",
            "create a authentication service",
            "实现订单管理功能",
            "build a REST API",
        ]
        for msg in code_msgs:
            intent = router._rule_based_classify(msg)
            assert intent == "code_generation", f"Failed for: {msg}"

    def test_classify_code_fix(self):
        """code_fix 意图分类。"""
        router = SupervisorRouter()

        fix_msgs = [
            "登录功能有 bug，修复一下",
            "fix the authentication error",
            "代码出了问题",
            "debug the module",
        ]
        for msg in fix_msgs:
            intent = router._rule_based_classify(msg)
            assert intent == "code_fix", f"Failed for: {msg}"

    def test_classify_quality_check(self):
        """quality_check 意图分类。"""
        router = SupervisorRouter()

        quality_msgs = [
            "检查代码质量",
            "run quality review",
            "审查这个模块",
            "test the code",
        ]
        for msg in quality_msgs:
            intent = router._rule_based_classify(msg)
            assert intent == "quality_check", f"Failed for: {msg}"

    def test_classify_knowledge_query(self):
        """knowledge_query 意图分类。"""
        router = SupervisorRouter()

        knowledge_msgs = [
            "什么是用户认证？",
            "how to implement auth",
            "什么是 JWT？",
            "help me understand modules",
        ]
        for msg in knowledge_msgs:
            intent = router._rule_based_classify(msg)
            assert intent == "knowledge_query", f"Failed for: {msg}"

    def test_classify_approval_action(self):
        """approval_action 意图分类。"""
        router = SupervisorRouter()

        approval_msgs = [
            "审批这个请求",
            "approve the deployment",
            "拒绝这个操作",
            "reject the change",
        ]
        for msg in approval_msgs:
            intent = router._rule_based_classify(msg)
            assert intent == "approval_action", f"Failed for: {msg}"

    def test_classify_with_injected_classifier(self):
        """使用注入的 IntentClassifier。"""
        from tools.rag.cognitive.rag_cognitive import IntentClassifier

        classifier = IntentClassifier()
        router = SupervisorRouter(intent_classifier=classifier)

        intent = router._classify_intent("帮我生成代码")
        # IntentClassifier 返回 IntentResult，primary_intent 可能是 "code_generation"
        assert isinstance(intent, str)


# ---------------------------------------------------------------------------
# Tests: Route Method
# ---------------------------------------------------------------------------

class TestRoute:
    @pytest.mark.asyncio
    async def test_route_code_generation(self):
        """code_generation 意图路由。"""
        llm = MockLLMProvider()
        router = SupervisorRouter(llm_provider=llm)
        state = await router.route("帮我生成用户登录模块")

        assert state.intent == "code_generation"
        assert state.stop_reason != StopReason.NONE

    @pytest.mark.asyncio
    async def test_route_knowledge_query(self):
        """knowledge_query 意图路由。"""
        router = SupervisorRouter()
        state = await router.route("什么是用户认证？")

        assert state.intent == "knowledge_query"
        assert state.stop_reason == StopReason.ANSWERED
        assert "知识库" in state.reply

    @pytest.mark.asyncio
    async def test_route_code_fix(self):
        """code_fix 意图路由。"""
        router = SupervisorRouter()
        state = await router.route("修复登录 bug")

        assert state.intent == "code_fix"
        assert state.stop_reason == StopReason.ANSWERED

    @pytest.mark.asyncio
    async def test_route_quality_check(self):
        """quality_check 意图路由。"""
        router = SupervisorRouter()
        state = await router.route("检查代码质量")

        assert state.intent == "quality_check"
        assert state.stop_reason == StopReason.ANSWERED

    @pytest.mark.asyncio
    async def test_route_approval_action(self):
        """approval_action 意图路由。"""
        router = SupervisorRouter()
        state = await router.route("审批这个请求")

        assert state.intent == "approval_action"

    @pytest.mark.asyncio
    async def test_route_unknown_intent_fallback(self):
        """未知意图 fallback。"""
        router = SupervisorRouter()
        # 空消息应该 fallback 到 knowledge_query（默认）
        state = await router.route("")

        # 空消息会 fallback 到 knowledge_query
        assert state.intent == "knowledge_query"

    @pytest.mark.asyncio
    async def test_route_sets_state_fields(self):
        """route 正确设置 state 各字段。"""
        llm = MockLLMProvider()
        router = SupervisorRouter(llm_provider=llm)
        state = await router.route("帮我生成模块")

        assert state.intent != ""
        assert state.stop_reason != StopReason.NONE
        assert len(state.trace) > 0  # trace 记录了处理过程

    @pytest.mark.asyncio
    async def test_route_preserves_conversation_history(self):
        """多轮对话时保留历史。"""
        llm = MockLLMProvider()
        router = SupervisorRouter(llm_provider=llm)

        # 第一轮
        state = await router.route("帮我生成用户登录模块")
        initial_history_len = len(state.history)

        # 第二轮（传入已有 state）
        state2 = await router.route("再添加权限控制", state=state)
        assert len(state2.history) >= initial_history_len + 1

    @pytest.mark.asyncio
    async def test_route_adds_assistant_reply_to_history(self):
        """assistant 回复被添加到 history。"""
        router = SupervisorRouter()
        state = await router.route("什么是认证？")

        # 检查 history 中有 assistant 消息
        assistant_msgs = [m for m in state.history if m.role == "assistant"]
        assert len(assistant_msgs) >= 1

    @pytest.mark.asyncio
    async def test_route_with_existing_state(self):
        """传入已有 state 时更新而非重建。"""
        router = SupervisorRouter()
        existing_state = create_agent_state("initial message", conversation_id="conv-123")
        existing_state.add_message("assistant", "previous reply")

        new_state = await router.route("new question", state=existing_state)

        assert new_state.conversation_id == "conv-123"
        assert len(new_state.history) >= 3  # user + assistant + new user (+ possibly new assistant)
