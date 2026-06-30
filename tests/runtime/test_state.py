# tests/runtime/test_state.py

"""
tests/runtime/test_state.py — AgentState 单元测试。

覆盖：默认值、工厂函数、消息添加工具记录、步数控制、终止条件。
"""

from __future__ import annotations

import pytest
from agents.runtime.state import (
    AgentState,
    Message,
    ToolCallRecord,
    StopReason,
    create_agent_state,
)


# ---------------------------------------------------------------------------
# 默认值与工厂函数
# ---------------------------------------------------------------------------

class TestCreateAgentState:
    def test_create_agent_state_defaults(self):
        """工厂函数创建默认 AgentState。"""
        state = create_agent_state("hello")
        assert state.message == "hello"
        assert state.conversation_id != ""
        assert state.intent == ""
        assert state.step_count == 0
        assert state.stop_reason == StopReason.NONE
        assert state.max_steps == 10

    def test_create_agent_state_with_conversation_id(self):
        """提供 conversation_id 时直接使用。"""
        state = create_agent_state("test", conversation_id="conv-123")
        assert state.conversation_id == "conv-123"

    def test_create_agent_state_generates_uuid(self):
        """不提供 conversation_id 时自动生成。"""
        state = create_agent_state("test")
        # UUID v4 格式：xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx
        assert len(state.conversation_id) == 36
        assert state.conversation_id[14] == "4"

    def test_create_agent_state_with_message(self):
        """message 正确赋值并自动添加到 history。"""
        state = create_agent_state("用户登录模块")
        assert state.message == "用户登录模块"
        assert len(state.history) == 1
        assert state.history[0].role == "user"
        assert state.history[0].content == "用户登录模块"

    def test_create_agent_state_with_kwargs(self):
        """kwargs 覆盖默认字段值。"""
        state = create_agent_state("test", intent="code_generation", max_steps=5)
        assert state.intent == "code_generation"
        assert state.max_steps == 5


# ---------------------------------------------------------------------------
# 消息管理
# ---------------------------------------------------------------------------

class TestAgentStateMessages:
    def test_add_message(self):
        """add_message 追加消息到 history。"""
        state = AgentState()
        msg = state.add_message("assistant", "Hello!")
        assert len(state.history) == 1
        assert msg.role == "assistant"
        assert msg.content == "Hello!"
        assert msg.metadata == {}

    def test_add_message_with_metadata(self):
        """add_message 支持 metadata。"""
        state = AgentState()
        state.add_message("tool", "result", metadata={"tool": "search"})
        assert state.history[0].metadata == {"tool": "search"}

    def test_message_dataclass(self):
        """Message dataclass 字段正确。"""
        msg = Message(role="user", content="hi", metadata={"k": "v"})
        assert msg.role == "user"
        assert msg.content == "hi"
        assert msg.metadata == {"k": "v"}


# ---------------------------------------------------------------------------
# 工具记录
# ---------------------------------------------------------------------------

class TestAgentStateToolRecord:
    def test_add_tool_record(self):
        """add_tool_record 追加记录并更新 tool_results。"""
        state = AgentState()
        record = state.add_tool_record("search", {"q": "test"}, ["doc1"], True, 100)
        assert len(state.tool_history) == 1
        assert record.tool_name == "search"
        assert record.arguments == {"q": "test"}
        assert record.result == ["doc1"]
        assert record.success is True
        assert record.duration_ms == 100
        assert state.tool_results["search"] == ["doc1"]

    def test_add_multiple_tool_records(self):
        """多次添加工具记录按序保存。"""
        state = AgentState()
        state.add_tool_record("t1", {}, "r1", True)
        state.add_tool_record("t2", {}, "r2", False)
        assert len(state.tool_history) == 2
        assert state.tool_history[0].tool_name == "t1"
        assert state.tool_history[1].tool_name == "t2"

    def test_tool_call_record_creation(self):
        """ToolCallRecord dataclass 字段正确。"""
        record = ToolCallRecord(
            tool_name="compile",
            arguments={"module": "auth"},
            result={"status": "ok"},
            success=True,
            duration_ms=50,
        )
        assert record.tool_name == "compile"
        assert record.duration_ms == 50


# ---------------------------------------------------------------------------
# 步数控制
# ---------------------------------------------------------------------------

class TestAgentStateStepControl:
    def test_step_increment(self):
        """increment_step 递增 step_count。"""
        state = AgentState()
        assert state.step_count == 0
        state.increment_step()
        assert state.step_count == 1
        state.increment_step()
        assert state.step_count == 2

    def test_max_steps_not_exceeded(self):
        """未超过 max_steps 时 check_max_steps 返回 False。"""
        state = AgentState(max_steps=3)
        state.step_count = 2
        assert state.check_max_steps() is False
        assert state.stop_reason == StopReason.NONE

    def test_max_steps_exceeded(self):
        """超过 max_steps 时 check_max_steps 设置 stop_reason。"""
        state = AgentState(max_steps=3)
        state.step_count = 3
        assert state.check_max_steps() is True
        assert state.stop_reason == StopReason.MAX_STEPS

    def test_max_steps_over(self):
        """超过 max_steps 时正确触发。"""
        state = AgentState(max_steps=5)
        state.step_count = 10
        assert state.check_max_steps() is True


# ---------------------------------------------------------------------------
# 终止条件
# ---------------------------------------------------------------------------

class TestAgentStateStopConditions:
    def test_should_stop_initially_false(self):
        """初始状态 should_stop 为 False。"""
        state = AgentState()
        assert state.should_stop() is False

    def test_should_stop_when_answered(self):
        """stop_reason 设置为 answered 时 should_stop 为 True。"""
        state = AgentState()
        state.stop_reason = StopReason.ANSWERED
        assert state.should_stop() is True

    def test_should_stop_when_max_steps(self):
        """stop_reason 设置为 max_steps 时 should_stop 为 True。"""
        state = AgentState()
        state.stop_reason = StopReason.MAX_STEPS
        assert state.should_stop() is True

    def test_should_stop_when_error(self):
        """stop_reason 设置为 error 时 should_stop 为 True。"""
        state = AgentState()
        state.stop_reason = StopReason.ERROR
        assert state.should_stop() is True

    def test_stop_reason_constants(self):
        """StopReason 常量值正确。"""
        assert StopReason.NONE == ""
        assert StopReason.ANSWERED == "answered"
        assert StopReason.NEED_MORE_INFO == "need_more_info"
        assert StopReason.WAITING_HUMAN == "waiting_human"
        assert StopReason.MAX_STEPS == "max_steps"
        assert StopReason.ERROR == "error"


# ---------------------------------------------------------------------------
# Trace 记录
# ---------------------------------------------------------------------------

class TestAgentStateTrace:
    def test_add_trace(self):
        """add_trace 追加 trace 条目。"""
        state = AgentState()
        entry = state.add_trace("intent_classified", {"intent": "code_gen"})
        assert len(state.trace) == 1
        assert entry["event"] == "intent_classified"
        assert entry["step"] == 0
        assert entry["data"] == {"intent": "code_gen"}

    def test_trace_records_step(self):
        """trace 条目记录当前 step_count。"""
        state = AgentState()
        state.increment_step()
        state.increment_step()
        entry = state.add_trace("tool_executed")
        assert entry["step"] == 2
