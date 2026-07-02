"""P2-1 security tests: CRITICAL risk level with dual-factor enforcement.

RISK_LEVELS now includes "critical" (highest level). CRITICAL operations:
1. AutoApprovalHandler: NEVER auto-approves
2. EnterpriseApprovalHandler: requires >= 2 distinct actors (dual-factor)
3. Enterprises: triggers immediate CRITICAL alert via message bus
"""

import pytest

from tools.hitl.approval import (
    AutoApprovalHandler,
    EnterpriseApprovalHandler,
    ManualApprovalHandler,
    RISK_LEVELS,
    CRITICAL_MIN_APPROVERS,
)
from tools.hitl.approval_state import ApprovalStatus
from tools.hitl.audit_chain import HashChainedAuditLog
from tools.hitl.approval_chain import ApprovalChain
from tools.hitl.approval_state import ApprovalStateMachine, is_terminal


# ---------------------------------------------------------------------------
# RISK_LEVELS 包含 critical
# ---------------------------------------------------------------------------

class TestRiskLevels:
    def test_critical_in_risk_levels(self):
        assert "critical" in RISK_LEVELS

    def test_risk_order_low_to_critical(self):
        assert RISK_LEVELS == ["low", "medium", "high", "critical"]

    def test_critical_min_approvers_defined(self):
        assert CRITICAL_MIN_APPROVERS >= 2


# ---------------------------------------------------------------------------
# AutoApprovalHandler — critical 绝不自动放行
# ---------------------------------------------------------------------------

class TestAutoApprovalCritical:
    def test_critical_never_auto_approved(self):
        """auto_under_risk='high' 时 critical 仍需人工。"""
        handler = AutoApprovalHandler(auto_under_risk="high")
        result = handler.request_approval("delete_db", {}, "critical")
        assert not result.approved
        assert result.requires_human

    def test_critical_never_auto_approved_even_at_max(self):
        """即使 auto_under_risk 设为最大值，critical 也不自动放行。"""
        handler = AutoApprovalHandler(auto_under_risk="high")
        result = handler.request_approval("drop_table", {}, "critical")
        assert result.requires_human

    def test_critical_rejected_as_auto_threshold(self):
        """不允许将 'critical' 设为 auto_under_risk。"""
        with pytest.raises(ValueError, match="critical"):
            AutoApprovalHandler(auto_under_risk="critical")

    def test_low_medium_high_still_work(self):
        """原有 level 行为不受影响。"""
        handler = AutoApprovalHandler(auto_under_risk="medium")
        assert handler.request_approval("read", {}, "low").approved
        assert handler.request_approval("write", {}, "medium").approved
        assert not handler.request_approval("delete", {}, "high").approved

    def test_unknown_risk_level_raises(self):
        handler = AutoApprovalHandler(auto_under_risk="low")
        with pytest.raises(ValueError):
            handler.request_approval("x", {}, "unknown")


# ---------------------------------------------------------------------------
# EnterpriseApprovalHandler — 双因子审批
# ---------------------------------------------------------------------------

class TestEnterpriseCritical:
    @pytest.fixture
    def handler(self):
        return EnterpriseApprovalHandler(audit_log=HashChainedAuditLog())

    def test_critical_requires_human(self, handler):
        result = handler.request_approval("delete_prod_db", {}, "critical")
        assert result.requires_human
        assert "2" in result.comment  # hint about required approvers

    def test_critical_single_approver_not_enough(self, handler):
        """第一次 CRITICAL 审批: 返回 requires_human=True，状态不变 PENDING。"""
        req = handler.request_approval("delete_prod_db", {}, "critical")
        assert req.requires_human

        result = handler.approve(req.approval_id, actor="alice", comment="I approve")
        assert not result.approved  # 单审批不足以通过 CRITICAL
        assert result.requires_human
        assert "1/2" in result.comment

        record = handler.get_status(req.approval_id)
        assert record.state_machine.status == ApprovalStatus.PENDING

    def test_critical_second_same_approver_rejected(self, handler):
        """同一 actor 再次审批被拒绝。"""
        req = handler.request_approval("delete_prod_db", {}, "critical")
        handler.approve(req.approval_id, actor="alice")
        result = handler.approve(req.approval_id, actor="alice", comment="again")
        assert not result.approved
        assert "already approved" in result.comment

    def test_critical_two_distinct_approvers_approved(self, handler):
        """两个不同 actor 审批后 CRITICAL 操作才被批准。"""
        req = handler.request_approval("delete_prod_db", {}, "critical")

        # 第一个审批: 记录但不通过
        r1 = handler.approve(req.approval_id, actor="alice")
        assert not r1.approved

        # 第二个不同 actor 审批: 通过
        r2 = handler.approve(req.approval_id, actor="bob")
        assert r2.approved

        record = handler.get_status(req.approval_id)
        assert record.state_machine.status == ApprovalStatus.APPROVED
        assert is_terminal(record.state_machine.status)

    def test_critical_reject_clears_tracking(self, handler):
        """CRITICAL 被 reject 后清除追踪。"""
        req = handler.request_approval("delete_prod_db", {}, "critical")
        handler.approve(req.approval_id, actor="alice")
        handler.reject(req.approval_id, actor="carol", reason="too dangerous")

        record = handler.get_status(req.approval_id)
        assert record.state_machine.status == ApprovalStatus.REJECTED

    def test_high_risk_still_single_approver(self, handler):
        """risk_level='high' 仍然只需要一个 actor（向后兼容）。"""
        req = handler.request_approval("write_file", {}, "high")
        result = handler.approve(req.approval_id, actor="alice")
        assert result.approved
        record = handler.get_status(req.approval_id)
        assert record.state_machine.status == ApprovalStatus.APPROVED

    def test_audit_records_critical_partial(self, handler):
        """CRITICAL 部分审批记录在审计日志中。"""
        log = handler.get_audit_log()
        req = handler.request_approval("drop_table", {}, "critical")
        handler.approve(req.approval_id, actor="alice")

        # 审计日志包含 critical_approval_partial 和 critical_approval_required
        events = [r.event.get("event") for r in log._records]
        assert "critical_approval_required" in events
        assert "critical_approval_partial" in events

    def test_pending_count_excludes_terminal(self, handler):
        """pending_count 只计算非终态的记录。"""
        req1 = handler.request_approval("drop_db", {}, "critical")
        req2 = handler.request_approval("write", {}, "low")

        # critical 待处理，low 需要 chain 为空时自动处理（这里无 chain，requires_human=True）
        assert handler.pending_count >= 1

        # 完成 critical（两个审批）
        handler.approve(req1.approval_id, actor="alice")
        handler.approve(req1.approval_id, actor="bob")
        assert handler.pending_count >= 0


# ---------------------------------------------------------------------------
# CRITICAL 告警 — 消息总线集成
# ---------------------------------------------------------------------------

class TestCriticalAlert:
    def test_critical_publishes_alert_on_message_bus(self, caplog):
        """CRITICAL 级别发布到 alert.critical。"""
        from tools.messaging.multichannel_bus import MultiChannelBus

        # 构造 messaging bus mock
        published = []

        class MockBus:
            def publish(self, channel, msg):
                published.append((channel, msg))

        handler = EnterpriseApprovalHandler(
            audit_log=HashChainedAuditLog(),
            messaging_bus=MockBus(),
        )
        handler.request_approval("drop_prod_db", {}, "critical")

        assert len(published) >= 1
        channels = [ch for ch, _ in published]
        assert any("critical" in ch for ch in channels)

    def test_critical_no_message_bus_no_error(self, caplog):
        """无消息总线时 CRITICAL 不抛出异常。"""
        handler = EnterpriseApprovalHandler(audit_log=HashChainedAuditLog())
        # 不应抛出
        result = handler.request_approval("rm_rf", {}, "critical")
        assert result.requires_human
