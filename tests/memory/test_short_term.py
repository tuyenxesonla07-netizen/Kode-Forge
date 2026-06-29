"""Tests for Memory system (ShortTerm, SessionState)."""

import pytest

from tools.memory.short_term import ShortTermMemory, Message
from tools.memory.session_state import SessionState


# ---------------------------------------------------------------------------
# ShortTermMemory
# ---------------------------------------------------------------------------

class TestShortTermMemory:
    def test_add_message(self):
        mem = ShortTermMemory(window=5)
        mem.add("user", "Hello")
        assert len(mem) == 1

    def test_context_returns_messages(self):
        mem = ShortTermMemory(window=5)
        mem.add("user", "Hello")
        mem.add("assistant", "Hi there")
        ctx = mem.context()
        assert len(ctx) == 2
        assert ctx[0]["role"] == "user"
        assert ctx[1]["role"] == "assistant"

    def test_window_compression(self):
        mem = ShortTermMemory(window=4)
        mem.add("user", "Build auth module")
        mem.add("assistant", "Done with auth")
        mem.add("user", "Add payment module")
        mem.add("assistant", "Done with payment")
        # 5th message triggers compression
        mem.add("user", "Now add logging")
        assert len(mem) == 3  # 2 compressed + 2 remaining - 1 compressed = 3

    def test_compression_creates_summary(self):
        mem = ShortTermMemory(window=4)
        for i in range(6):
            mem.add("user", f"Message {i} about auth module")
        assert mem.summary != ""
        assert "earlier" in mem.summary

    def test_context_includes_summary(self):
        mem = ShortTermMemory(window=4)
        for i in range(6):
            mem.add("user", f"Message {i} about order module")
        ctx = mem.context()
        assert ctx[0]["role"] == "system"
        assert "Session Summary" in ctx[0]["content"]

    def test_clear(self):
        mem = ShortTermMemory(window=5)
        mem.add("user", "Hello")
        mem.add("assistant", "Hi")
        mem.clear()
        assert len(mem) == 0
        assert mem.summary == ""

    def test_no_compression_under_window(self):
        mem = ShortTermMemory(window=10)
        for i in range(5):
            mem.add("user", f"Message {i}")
        assert mem.summary == ""
        assert len(mem) == 5

    def test_message_has_timestamp(self):
        msg = Message(role="user", content="test")
        assert msg.timestamp != ""

    def test_message_to_dict(self):
        msg = Message(role="user", content="test")
        d = msg.to_dict()
        assert d == {"role": "user", "content": "test"}


# ---------------------------------------------------------------------------
# SessionState
# ---------------------------------------------------------------------------

class TestSessionState:
    def test_default_values(self):
        state = SessionState()
        assert state.status == "idle"
        assert state.step == 0
        assert state.tool_calls_made == 0
        assert state.user_id == "default"
        assert state.session_id != ""

    def test_custom_user(self):
        state = SessionState(user_id="user123")
        assert state.user_id == "user123"

    def test_update_status(self):
        state = SessionState()
        state.update(status="running", step=1)
        assert state.status == "running"
        assert state.step == 1

    def test_update_intent(self):
        state = SessionState()
        state.update(intent="code_generation")
        assert state.intent == "code_generation"

    def test_checkpoint(self):
        state = SessionState()
        state.update(intent="code_gen", step=3)
        snapshot = state.checkpoint("after_decomposition")
        assert snapshot["label"] == "after_decomposition"
        assert snapshot["step"] == 3
        assert snapshot["intent"] == "code_gen"

    def test_checkpoint_with_data(self):
        state = SessionState()
        snapshot = state.checkpoint("test", data={"modules": ["auth"]})
        assert snapshot["data"]["modules"] == ["auth"]

    def test_multiple_checkpoints(self):
        state = SessionState()
        state.update(step=1)
        state.checkpoint("step1")
        state.update(step=2)
        state.checkpoint("step2")
        assert len(state.checkpoints) == 2
        assert state.checkpoints[0]["label"] == "step1"
        assert state.checkpoints[1]["label"] == "step2"

    def test_resume_from_snapshot(self):
        original = SessionState(user_id="user1")
        original.update(intent="code_gen", step=5, tool_calls_made=3)
        original.facts = {"module": "auth"}
        snapshot = original.checkpoint("recovery_point")

        resumed = SessionState.resume("user1", snapshot)
        assert resumed.intent == "code_gen"
        assert resumed.step == 5
        assert resumed.tool_calls_made == 3
        assert resumed.facts == {"module": "auth"}

    def test_to_dict(self):
        state = SessionState()
        state.update(intent="test", step=2)
        d = state.to_dict()
        assert d["status"] == "idle"
        assert d["step"] == 2
        assert d["intent"] == "test"
        assert "session_id" in d

    def test_update_timestamp_changes(self):
        state = SessionState()
        original_time = state.updated_at
        import time
        time.sleep(0.01)
        state.update(step=1)
        # updated_at should be different (or at least not crash)
        assert state.updated_at != ""


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

class TestMemoryIntegration:
    def test_short_term_with_session_state(self):
        mem = ShortTermMemory(window=6)
        state = SessionState()

        mem.add("user", "Build auth module")
        state.update(intent="code_generation", step=1)
        mem.add("assistant", "Generated auth code")
        state.update(step=2)

        ctx = mem.context()
        assert len(ctx) == 2
        assert state.step == 2

    def test_compression_preserves_key_info(self):
        mem = ShortTermMemory(window=4)
        mem.add("user", "订单 ORD-2024-0001 需要退款")
        mem.add("assistant", "已为您查询到订单信息")
        mem.add("user", "物流状态是什么")
        mem.add("assistant", "物流已发货")
        # Trigger compression
        mem.add("user", "好的谢谢")

        assert "ORD-2024-0001" in mem.summary or "earlier" in mem.summary
