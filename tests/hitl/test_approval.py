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
