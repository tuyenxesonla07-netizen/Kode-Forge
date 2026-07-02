# tests/hitl/test_escalation.py

"""
Tests for tools.hitl.escalation — EscalationPolicy, SLATimer, EscalationState.
"""

import asyncio
from datetime import timedelta

import pytest

from tools.hitl.escalation import (
    EscalationPolicy,
    EscalationState,
    SLATimer,
)


# ── EscalationPolicy ───────────────────────────────────────────

class TestEscalationPolicy:

    def test_defaults(self):
        policy = EscalationPolicy()
        assert policy.max_escalations == 3
        assert policy.escalation_delay == timedelta(seconds=0)
        assert policy.notify_on_escalate is True
        assert policy.auto_approve_on_final is False

    def test_custom_values(self):
        policy = EscalationPolicy(
            max_escalations=5,
            escalation_delay=timedelta(hours=1),
            notify_on_escalate=False,
            auto_approve_on_final=True,
        )
        assert policy.max_escalations == 5
        assert policy.escalation_delay == timedelta(hours=1)
        assert policy.notify_on_escalate is False
        assert policy.auto_approve_on_final is True

    def test_zero_escalations_allowed(self):
        policy = EscalationPolicy(max_escalations=0)
        assert policy.max_escalations == 0

    def test_negative_max_escalations_raises(self):
        with pytest.raises(ValueError, match="max_escalations must be >= 0"):
            EscalationPolicy(max_escalations=-1)

    def test_negative_delay_raises(self):
        with pytest.raises(ValueError, match="escalation_delay must be non-negative"):
            EscalationPolicy(escalation_delay=timedelta(seconds=-1))


# ── SLATimer ───────────────────────────────────────────────────

class TestSLATimer:

    @pytest.mark.asyncio
    async def test_triggers_on_timeout(self):
        """SLA 超时后回调被触发。"""
        triggered = []

        async def on_timeout(approval_id, level):
            triggered.append((approval_id, level))

        timer = SLATimer(
            approval_id="req-1",
            level=1,
            sla=timedelta(milliseconds=50),
            on_timeout=on_timeout,
        )
        timer.start()
        await asyncio.sleep(0.15)  # 等待超时
        assert len(triggered) == 1
        assert triggered[0] == ("req-1", 1)

    @pytest.mark.asyncio
    async def test_cancel_prevents_timeout(self):
        """取消后回调不会被触发。"""
        triggered = []

        async def on_timeout(approval_id, level):
            triggered.append((approval_id, level))

        timer = SLATimer(
            approval_id="req-2",
            level=1,
            sla=timedelta(milliseconds=50),
            on_timeout=on_timeout,
        )
        timer.start()
        await asyncio.sleep(0.02)
        timer.cancel()
        await asyncio.sleep(0.1)  # 等待足够时间
        assert len(triggered) == 0

    @pytest.mark.asyncio
    async def test_is_running(self):
        """定时器启动后 is_running 为 True，超时后为 False。"""
        triggered = []

        async def on_timeout(approval_id, level):
            triggered.append((approval_id, level))

        timer = SLATimer(
            approval_id="req-3",
            level=1,
            sla=timedelta(milliseconds=50),
            on_timeout=on_timeout,
        )
        assert not timer.is_running
        timer.start()
        assert timer.is_running
        await asyncio.sleep(0.1)
        assert not timer.is_running

    @pytest.mark.asyncio
    async def test_double_start_raises(self):
        """重复启动定时器应抛出 RuntimeError。"""
        async def on_timeout(approval_id, level):
            pass

        timer = SLATimer(
            approval_id="req-4",
            level=1,
            sla=timedelta(hours=1),
            on_timeout=on_timeout,
        )
        timer.start()
        try:
            with pytest.raises(RuntimeError, match="already started"):
                timer.start()
        finally:
            timer.cancel()

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled(self):
        """重复取消不会报错。"""
        async def on_timeout(approval_id, level):
            pass

        timer = SLATimer(
            approval_id="req-5",
            level=1,
            sla=timedelta(milliseconds=50),
            on_timeout=on_timeout,
        )
        timer.start()
        timer.cancel()
        timer.cancel()  # 第二次取消不应报错
        await asyncio.sleep(0.01)


# ── EscalationState ────────────────────────────────────────────

class TestEscalationState:

    def test_default_state(self):
        state = EscalationState(approval_id="req-1")
        assert state.approval_id == "req-1"
        assert state.current_level == 1
        assert state.escalation_count == 0
        assert state.last_escalation_time is None

    def test_can_escalate_within_limit(self):
        policy = EscalationPolicy(max_escalations=3)
        state = EscalationState(approval_id="req-1")
        assert state.can_escalate(policy)
        state.escalation_count = 2
        assert state.can_escalate(policy)

    def test_cannot_escalate_at_limit(self):
        policy = EscalationPolicy(max_escalations=3)
        state = EscalationState(approval_id="req-1")
        state.escalation_count = 3
        assert not state.can_escalate(policy)

    def test_cannot_escalate_past_limit(self):
        policy = EscalationPolicy(max_escalations=2)
        state = EscalationState(approval_id="req-1")
        state.escalation_count = 5
        assert not state.can_escalate(policy)

    def test_record_escalation(self):
        state = EscalationState(approval_id="req-1")
        state.record_escalation(target_level=2)
        assert state.escalation_count == 1
        assert state.current_level == 2
        assert state.last_escalation_time is not None

    def test_record_multiple_escalations(self):
        state = EscalationState(approval_id="req-1")
        state.record_escalation(target_level=2)
        state.record_escalation(target_level=3)
        assert state.escalation_count == 2
        assert state.current_level == 3

    def test_zero_escalation_policy(self):
        """max_escalations=0 意味着不允许任何升级。"""
        policy = EscalationPolicy(max_escalations=0)
        state = EscalationState(approval_id="req-1")
        assert not state.can_escalate(policy)
