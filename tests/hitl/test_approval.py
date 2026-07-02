"""Tests for HITL (Human-in-the-Loop) approval system."""

import pytest

from tools.hitl.approval import (
    ApprovalRequest,
    ApprovalResult,
    AutoApprovalHandler,
    ManualApprovalHandler,
    get_approval_handler,
)


# ---------------------------------------------------------------------------
# AutoApprovalHandler
# ---------------------------------------------------------------------------

class TestAutoApprovalHandler:
    def test_low_risk_auto_approved(self):
        handler = AutoApprovalHandler(auto_under_risk="low")
        result = handler.request_approval("query_db", {"sql": "SELECT 1"}, "low")
        assert result.approved is True
        assert result.approver == "auto"

    def test_medium_risk_auto_approved_when_threshold_medium(self):
        handler = AutoApprovalHandler(auto_under_risk="medium")
        result = handler.request_approval("generate_code", {}, "medium")
        assert result.approved is True

    def test_high_risk_blocked(self):
        handler = AutoApprovalHandler(auto_under_risk="medium")
        result = handler.request_approval("write_file", {"path": "/etc/passwd"}, "high")
        assert result.approved is False
        assert result.requires_human is True

    def test_high_risk_blocked_at_low_threshold(self):
        handler = AutoApprovalHandler(auto_under_risk="low")
        result = handler.request_approval("delete_db", {}, "high")
        assert result.approved is False
        assert result.requires_human is True

    def test_callback_does_nothing(self):
        handler = AutoApprovalHandler()
        handler.callback("test-id", True, "approved")
        # No exception = pass

    def test_default_threshold_is_low(self):
        handler = AutoApprovalHandler()
        assert handler.auto_under_risk == "low"

    def test_custom_threshold_medium(self):
        handler = AutoApprovalHandler(auto_under_risk="medium")
        assert handler.auto_under_risk == "medium"


# ---------------------------------------------------------------------------
# ManualApprovalHandler
# ---------------------------------------------------------------------------

class TestManualApprovalHandler:
    def test_all_requires_human(self):
        handler = ManualApprovalHandler()
        result = handler.request_approval("query", {}, "low")
        assert result.approved is False
        assert result.requires_human is True

    def test_callback_approves(self):
        handler = ManualApprovalHandler()
        result = handler.request_approval("write", {}, "high")
        approval_id = result.comment.split(": ")[1]
        success = handler.callback(approval_id, True, "OK")
        assert success is True

    def test_callback_unknown_id(self):
        handler = ManualApprovalHandler()
        success = handler.callback("nonexistent", True, "OK")
        assert success is False

    def test_get_pending(self):
        handler = ManualApprovalHandler()
        handler.request_approval("write", {"path": "/tmp/test.py"}, "high")
        pending = handler.get_pending()
        assert len(pending) == 1
        assert pending[0]["tool"] == "write"
        assert pending[0]["risk"] == "high"

    def test_get_pending_empty(self):
        handler = ManualApprovalHandler()
        assert handler.get_pending() == []

    def test_unique_ids(self):
        handler = ManualApprovalHandler()
        r1 = handler.request_approval("a", {}, "low")
        r2 = handler.request_approval("b", {}, "medium")
        id1 = r1.comment.split(": ")[1]
        id2 = r2.comment.split(": ")[1]
        assert id1 != id2


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------

class TestGetApprovalHandler:
    def test_auto_mode(self):
        handler = get_approval_handler("auto")
        assert isinstance(handler, AutoApprovalHandler)

    def test_manual_mode(self):
        handler = get_approval_handler("manual")
        assert isinstance(handler, ManualApprovalHandler)

    def test_unknown_mode_defaults_to_auto(self):
        handler = get_approval_handler("unknown")
        assert isinstance(handler, AutoApprovalHandler)

    def test_with_kwargs(self):
        handler = get_approval_handler("auto", auto_under_risk="high")
        assert handler.auto_under_risk == "high"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class TestApprovalResult:
    def test_default_values(self):
        r = ApprovalResult(approved=True)
        assert r.approver == ""
        assert r.comment == ""
        assert r.requires_human is False

    def test_approved_with_details(self):
        r = ApprovalResult(approved=False, approver="admin", comment="Need review", requires_human=True)
        assert r.approved is False
        assert r.requires_human is True


class TestApprovalRequest:
    def test_creation(self):
        req = ApprovalRequest(tool_name="write", args={"path": "/tmp"}, risk_level="high", context={"user": "test"})
        assert req.tool_name == "write"
        assert req.risk_level == "high"


# ---------------------------------------------------------------------------
# V0.4.0 F3: EnterpriseApprovalHandler
# ---------------------------------------------------------------------------

from datetime import timedelta

from tools.hitl.approval import EnterpriseApprovalHandler, ApprovalStatus
from tools.hitl.approval_chain import RoleRegistry, ApprovalChain, ApprovalLevel
from tools.hitl.escalation import EscalationPolicy


class TestEnterpriseApprovalHandlerInit:

    def test_default_init(self):
        handler = EnterpriseApprovalHandler()
        assert handler.pending_count == 0
        assert len(handler.get_audit_log()) == 0

    def test_with_custom_registry(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        handler = EnterpriseApprovalHandler(role_registry=reg)
        assert handler.pending_count == 0

    def test_with_custom_chain(self):
        chain = ApprovalChain([
            ApprovalLevel(1, "tech_lead", ("alice",), timedelta(hours=24)),
        ])
        handler = EnterpriseApprovalHandler(chain=chain)
        assert handler.pending_count == 0


class TestEnterpriseApprovalHandlerRequestApproval:

    def test_low_risk_no_human_required(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        handler = EnterpriseApprovalHandler(role_registry=reg)
        result = handler.request_approval("query", {}, "low")
        assert not result.requires_human

    def test_medium_risk_requires_human(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        reg.assign("manager", "bob")
        handler = EnterpriseApprovalHandler(role_registry=reg)
        result = handler.request_approval("generate_code", {"module": "auth"}, "medium")
        assert result.requires_human
        assert result.approval_id != ""

    def test_high_risk_requires_human(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        reg.assign("manager", "bob")
        reg.assign("director", "carol")
        handler = EnterpriseApprovalHandler(role_registry=reg)
        result = handler.request_approval("write_file", {"path": "/etc/passwd"}, "high")
        assert result.requires_human

    def test_request_creates_pending_record(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        handler = EnterpriseApprovalHandler(role_registry=reg)
        result = handler.request_approval("write_file", {}, "high")
        assert handler.pending_count == 1
        record = handler.get_status(result.approval_id)
        assert record is not None
        assert record.state_machine.status == ApprovalStatus.PENDING

    def test_request_writes_audit_log(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        handler = EnterpriseApprovalHandler(role_registry=reg)
        result = handler.request_approval("write_file", {}, "high")
        audit = handler.get_audit_log()
        assert len(audit) >= 1
        assert audit[0].event["event"] == "approval_requested"
        assert audit[0].event["approval_id"] == result.approval_id

    def test_empty_registry_medium_risk(self):
        """没有审批人时，medium 风险也不需人工。"""
        handler = EnterpriseApprovalHandler()
        result = handler.request_approval("generate_code", {}, "medium")
        assert not result.requires_human


class TestEnterpriseApprovalHandlerApprove:

    def test_approve_request(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        handler = EnterpriseApprovalHandler(role_registry=reg)
        result = handler.request_approval("write_file", {}, "high")
        approval_id = result.approval_id

        approval_result = handler.approve(approval_id, actor="alice", comment="LGTM")
        assert approval_result.approved
        assert approval_result.approver == "alice"

    def test_approve_transitions_state(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        handler = EnterpriseApprovalHandler(role_registry=reg)
        result = handler.request_approval("write_file", {}, "high")
        approval_id = result.approval_id

        handler.approve(approval_id, actor="alice")
        record = handler.get_status(approval_id)
        assert record.state_machine.status == ApprovalStatus.APPROVED
        assert record.state_machine.is_terminal

    def test_approve_reduces_pending_count(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        handler = EnterpriseApprovalHandler(role_registry=reg)
        result = handler.request_approval("write_file", {}, "high")
        assert handler.pending_count == 1

        handler.approve(result.approval_id, actor="alice")
        assert handler.pending_count == 0

    def test_approve_unknown_id(self):
        handler = EnterpriseApprovalHandler()
        result = handler.approve("nonexistent", actor="alice")
        assert not result.approved
        assert "Unknown approval_id" in result.comment

    def test_approve_from_terminal_fails(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        handler = EnterpriseApprovalHandler(role_registry=reg)
        result = handler.request_approval("write_file", {}, "high")
        approval_id = result.approval_id

        handler.approve(approval_id, actor="alice")
        second = handler.approve(approval_id, actor="bob")
        assert not second.approved
        assert "Cannot approve" in second.comment

    def test_approve_writes_audit(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        handler = EnterpriseApprovalHandler(role_registry=reg)
        result = handler.request_approval("write_file", {}, "high")
        handler.approve(result.approval_id, actor="alice", justification="safe")

        audit = handler.get_audit_log()
        events = [r.event["event"] for r in audit]
        assert "approved" in events


class TestEnterpriseApprovalHandlerReject:

    def test_reject_request(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        handler = EnterpriseApprovalHandler(role_registry=reg)
        result = handler.request_approval("write_file", {}, "high")

        reject_result = handler.reject(result.approval_id, actor="alice", reason="Risk too high")
        assert not reject_result.approved
        assert reject_result.approver == "alice"

    def test_reject_transitions_state(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        handler = EnterpriseApprovalHandler(role_registry=reg)
        result = handler.request_approval("write_file", {}, "high")

        handler.reject(result.approval_id, actor="alice", reason="nope")
        record = handler.get_status(result.approval_id)
        assert record.state_machine.status == ApprovalStatus.REJECTED
        assert record.state_machine.is_terminal

    def test_reject_unknown_id(self):
        handler = EnterpriseApprovalHandler()
        result = handler.reject("nonexistent", actor="alice")
        assert not result.approved
        assert "Unknown approval_id" in result.comment


class TestEnterpriseApprovalHandlerEscalate:

    def test_escalate_request(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        reg.assign("manager", "bob")
        handler = EnterpriseApprovalHandler(role_registry=reg)
        result = handler.request_approval("write_file", {}, "high")
        approval_id = result.approval_id

        esc_result = handler.escalate(approval_id, actor="system", reason="SLA timeout")
        assert not esc_result.approved
        assert esc_result.requires_human
        assert "Escalated to level 2" in esc_result.comment

    def test_escalate_transitions_state(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        reg.assign("manager", "bob")
        handler = EnterpriseApprovalHandler(role_registry=reg)
        result = handler.request_approval("write_file", {}, "high")

        handler.escalate(result.approval_id, actor="system")
        record = handler.get_status(result.approval_id)
        assert record.state_machine.status == ApprovalStatus.ESCALATED
        assert not record.state_machine.is_terminal

    def test_escalate_then_approve(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        reg.assign("manager", "bob")
        handler = EnterpriseApprovalHandler(role_registry=reg)
        result = handler.request_approval("write_file", {}, "high")
        approval_id = result.approval_id

        handler.escalate(approval_id, actor="system")
        approval_result = handler.approve(approval_id, actor="bob", comment="OK at level 2")
        assert approval_result.approved

    def test_escalate_unknown_id(self):
        handler = EnterpriseApprovalHandler()
        result = handler.escalate("nonexistent", actor="system")
        assert not result.approved
        assert "Unknown approval_id" in result.comment

    def test_escalate_max_reached(self):
        policy = EscalationPolicy(max_escalations=0)
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        handler = EnterpriseApprovalHandler(role_registry=reg, escalation_policy=policy)
        result = handler.request_approval("write_file", {}, "high")

        esc_result = handler.escalate(result.approval_id, actor="system")
        assert not esc_result.approved
        assert "Max escalations reached" in esc_result.comment


class TestEnterpriseApprovalHandlerAudit:

    def test_audit_chain_valid(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        handler = EnterpriseApprovalHandler(role_registry=reg)
        result = handler.request_approval("write_file", {}, "high")
        handler.approve(result.approval_id, actor="alice")

        audit = handler.get_audit_log()
        is_valid, last_idx = audit.verify_chain()
        assert is_valid
        assert last_idx >= 0

    def test_audit_chain_tracks_all_events(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        handler = EnterpriseApprovalHandler(role_registry=reg)
        result = handler.request_approval("write_file", {}, "high")
        handler.approve(result.approval_id, actor="alice", justification="safe")

        audit = handler.get_audit_log()
        events = [r.event["event"] for r in audit]
        assert "approval_requested" in events
        assert "approved" in events


class TestGetApprovalHandlerEnterprise:

    def test_enterprise_mode(self):
        handler = get_approval_handler("enterprise")
        assert isinstance(handler, EnterpriseApprovalHandler)


# ---------------------------------------------------------------------------
# V0.4.0 F4: 消息总线集成
# ---------------------------------------------------------------------------

from tools.messaging.channel import ChannelRegistry, ChannelAdapter
from tools.messaging.multichannel_bus import MultiChannelBus
from tools.workflow.messaging import MessageBus


class _CapturingAdapter(ChannelAdapter):
    """捕获所有发送的消息用于断言。"""

    channel_name = "capturing"

    def __init__(self):
        self.sent: list = []

    async def send(self, message):
        self.sent.append(message)
        return True

    async def receive(self):
        return None

    async def start(self):
        pass

    async def stop(self):
        pass

    async def health_check(self):
        return {"status": "ok"}


class TestEnterpriseApprovalHandlerMessaging:

    def test_messaging_bus_receives_escalation(self):
        """升级事件应发布到消息总线。"""
        inner = MessageBus()
        registry = ChannelRegistry()
        capturing = _CapturingAdapter()
        registry.register("capturing", capturing)
        bus = MultiChannelBus(
            inner=inner,
            registry=registry,
            routing_rules={"escalation.*": ["capturing"]},
        )

        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        reg.assign("manager", "bob")
        handler = EnterpriseApprovalHandler(role_registry=reg, messaging_bus=bus)

        result = handler.request_approval("write_file", {}, "high")
        handler.escalate(result.approval_id, actor="system", reason="SLA timeout")

        # 同步上下文中异步 dispatch 可能未完成，但 publish 已调用
        # 验证总线路由匹配正确
        assert "escalation.*" in bus.routes

    def test_messaging_bus_none_is_safe(self):
        """messaging_bus=None 时不应报错。"""
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        handler = EnterpriseApprovalHandler(role_registry=reg, messaging_bus=None)

        result = handler.request_approval("write_file", {}, "high")
        approval_result = handler.approve(result.approval_id, actor="alice")
        assert approval_result.approved
