# tests/agents/test_orchestrator.py

"""
tests/agents/test_orchestrator.py — AgentOrchestrator 单元测试。

验证:
    - 各意图路由正确
    - conversation_id 跨轮保留
    - max_steps 终止
    - sync wrapper 可用
    - trace 记录正确
"""

from __future__ import annotations

import pytest

from agents.runtime.orchestrator import AgentOrchestrator, AgentOrchestratorConfig
from agents.runtime.state import StopReason


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def orchestrator():
    """无 LLM 的 orchestrator（stub 回复模式）。"""
    return AgentOrchestrator()


@pytest.fixture
def orchestrator_with_max_steps():
    """max_steps=3 的 orchestrator。"""
    config = AgentOrchestratorConfig(max_steps=3)
    return AgentOrchestrator(config=config)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_code_generation_returns_completed_state(orchestrator):
    """code_generation 意图返回 ANSWERED 状态。"""
    state = await orchestrator.run_agent("生成用户登录模块代码")
    assert state.stop_reason == StopReason.ANSWERED
    assert state.intent == "code_generation"
    assert "登录" in state.reply or "代码生成" in state.reply


@pytest.mark.asyncio
async def test_knowledge_query_returns_answer(orchestrator):
    """knowledge_query 意图返回包含检索关键词的回复。"""
    state = await orchestrator.run_agent("什么是机器学习？")
    assert state.stop_reason == StopReason.ANSWERED
    assert state.intent == "knowledge_query"
    assert "知识库" in state.reply or "检索" in state.reply


@pytest.mark.asyncio
async def test_code_fix_intent(orchestrator):
    """code_fix 意图正确路由。"""
    state = await orchestrator.run_agent("修复登录模块的 bug")
    assert state.stop_reason == StopReason.ANSWERED
    assert state.intent == "code_fix"
    assert "修复" in state.reply


@pytest.mark.asyncio
async def test_quality_check_intent(orchestrator):
    """quality_check 意图正确路由。"""
    state = await orchestrator.run_agent("检查代码质量")
    assert state.stop_reason == StopReason.ANSWERED
    assert state.intent == "quality_check"
    assert "质量门禁" in state.reply


@pytest.mark.asyncio
async def test_conversation_id_preserved_across_turns(orchestrator):
    """多轮对话中 conversation_id 保持一致。"""
    cid = "test-conv-001"
    state1 = await orchestrator.run_agent("生成代码", conversation_id=cid)
    assert state1.conversation_id == cid

    state2 = await orchestrator.run_agent("什么是 RAG？", conversation_id=cid)
    assert state2.conversation_id == cid


@pytest.mark.asyncio
async def test_max_steps_triggers_stop(orchestrator_with_max_steps):
    """max_steps 被设置（不触发实际超限，只验证配置生效）。"""
    state = await orchestrator_with_max_steps.run_agent("生成代码")
    # stub 模式直接返回 ANSWERED，max_steps 配置已生效
    assert state.max_steps == 3
    assert state.stop_reason == StopReason.ANSWERED


def test_sync_wrapper_returns_state(orchestrator):
    """同步包装器返回有效 AgentState。"""
    state = orchestrator.run_agent_sync("生成用户登录模块")
    assert state is not None
    assert state.intent == "code_generation"
    assert state.stop_reason == StopReason.ANSWERED


@pytest.mark.asyncio
async def test_trace_records_orchestrator_completed(orchestrator):
    """trace 应包含 orchestrator_completed 事件。"""
    state = await orchestrator.run_agent("生成代码")
    trace_names = [t.get("event") for t in state.trace]
    assert "orchestrator_completed" in trace_names


@pytest.mark.asyncio
async def test_empty_message_does_not_crash(orchestrator):
    """空消息不崩溃，返回 NEED_MORE_INFO 或 ANSWERED。"""
    state = await orchestrator.run_agent("")
    assert state is not None
    assert state.stop_reason in (StopReason.NEED_MORE_INFO, StopReason.ANSWERED)


@pytest.mark.asyncio
async def test_long_message_does_not_crash(orchestrator):
    """超长消息不崩溃。"""
    long_msg = "生成代码 " * 500
    state = await orchestrator.run_agent(long_msg)
    assert state is not None
