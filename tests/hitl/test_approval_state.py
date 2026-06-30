# tests/hitl/test_approval_state.py

"""
Tests for tools.hitl.approval_state — ApprovalStatus, ApprovalStateMachine.
"""

import pytest

from tools.hitl.approval_state import (
    ApprovalStatus,
    ApprovalStateMachine,
    InvalidTransitionError,
    TERMINAL_STATES,
    VALID_TRANSITIONS,
    can_transition,
    is_terminal,
)


# ── ApprovalStatus enum ─────────────────────────────────────────

class TestApprovalStatus:

    def test_enum_values(self):
        assert ApprovalStatus.PENDING.value == "pending"
        assert ApprovalStatus.APPROVED.value == "approved"
        assert ApprovalStatus.REJECTED.value == "rejected"
        assert ApprovalStatus.ESCALATED.value == "escalated"
        assert ApprovalStatus.EXPIRED.value == "expired"

    def test_enum_is_str_subclass(self):
        """ApprovalStatus 继承 str，可以直接比较字符串。"""
        assert ApprovalStatus.PENDING == "pending"
        assert "pending" == ApprovalStatus.PENDING


# ── is_terminal ─────────────────────────────────────────────────

class TestIsTerminal:

    def test_pending_not_terminal(self):
        assert not is_terminal(ApprovalStatus.PENDING)

    def test_escalated_not_terminal(self):
        assert not is_terminal(ApprovalStatus.ESCALATED)

    def test_approved_is_terminal(self):
        assert is_terminal(ApprovalStatus.APPROVED)

    def test_rejected_is_terminal(self):
        assert is_terminal(ApprovalStatus.REJECTED)

    def test_expired_is_terminal(self):
        assert is_terminal(ApprovalStatus.EXPIRED)

    def test_terminal_states_frozen(self):
        assert TERMINAL_STATES == {
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.EXPIRED,
        }


# ── can_transition ──────────────────────────────────────────────

class TestCanTransition:

    def test_pending_to_approved(self):
        assert can_transition(ApprovalStatus.PENDING, ApprovalStatus.APPROVED)

    def test_pending_to_rejected(self):
        assert can_transition(ApprovalStatus.PENDING, ApprovalStatus.REJECTED)

    def test_pending_to_escalated(self):
        assert can_transition(ApprovalStatus.PENDING, ApprovalStatus.ESCALATED)

    def test_pending_to_expired(self):
        assert can_transition(ApprovalStatus.PENDING, ApprovalStatus.EXPIRED)

    def test_pending_to_pending_not_allowed(self):
        assert not can_transition(ApprovalStatus.PENDING, ApprovalStatus.PENDING)

    def test_escalated_to_approved(self):
        assert can_transition(ApprovalStatus.ESCALATED, ApprovalStatus.APPROVED)

    def test_escalated_to_rejected(self):
        assert can_transition(ApprovalStatus.ESCALATED, ApprovalStatus.REJECTED)

    def test_escalated_to_expired(self):
        assert can_transition(ApprovalStatus.ESCALATED, ApprovalStatus.EXPIRED)

    def test_escalated_cannot_re_escalate(self):
        assert not can_transition(ApprovalStatus.ESCALATED, ApprovalStatus.ESCALATED)

    def test_terminal_states_cannot_transition(self):
        """终态不能转换到任何状态。"""
        for status in TERMINAL_STATES:
            for target in ApprovalStatus:
                assert not can_transition(status, target), f"{status} → {target}"


# ── ApprovalStateMachine ────────────────────────────────────────

class TestApprovalStateMachineInit:

    def test_default_initial_state(self):
        sm = ApprovalStateMachine()
        assert sm.status == ApprovalStatus.PENDING

    def test_history_starts_with_pending(self):
        sm = ApprovalStateMachine()
        assert sm.history == [(ApprovalStatus.PENDING, None)]

    def test_non_pending_initial_raises(self):
        with pytest.raises(ValueError, match="Initial state must be PENDING"):
            ApprovalStateMachine(initial=ApprovalStatus.APPROVED)


class TestApprovalStateMachineTransition:

    def test_pending_to_approved(self):
        sm = ApprovalStateMachine()
        sm.transition(ApprovalStatus.APPROVED)
        assert sm.status == ApprovalStatus.APPROVED
        assert sm.is_terminal

    def test_pending_to_rejected(self):
        sm = ApprovalStateMachine()
        sm.transition(ApprovalStatus.REJECTED)
        assert sm.status == ApprovalStatus.REJECTED
        assert sm.is_terminal

    def test_pending_to_escalated_to_approved(self):
        sm = ApprovalStateMachine()
        sm.transition(ApprovalStatus.ESCALATED)
        assert sm.status == ApprovalStatus.ESCALATED
        assert not sm.is_terminal
        sm.transition(ApprovalStatus.APPROVED)
        assert sm.status == ApprovalStatus.APPROVED
        assert sm.is_terminal

    def test_pending_to_escalated_to_rejected(self):
        sm = ApprovalStateMachine()
        sm.transition(ApprovalStatus.ESCALATED)
        sm.transition(ApprovalStatus.REJECTED)
        assert sm.status == ApprovalStatus.REJECTED

    def test_pending_to_escalated_to_expired(self):
        sm = ApprovalStateMachine()
        sm.transition(ApprovalStatus.ESCALATED)
        sm.transition(ApprovalStatus.EXPIRED)
        assert sm.status == ApprovalStatus.EXPIRED
        assert sm.is_terminal

    def test_pending_to_expired(self):
        sm = ApprovalStateMachine()
        sm.transition(ApprovalStatus.EXPIRED)
        assert sm.status == ApprovalStatus.EXPIRED
        assert sm.is_terminal

    def test_invalid_transition_raises(self):
        sm = ApprovalStateMachine()
        with pytest.raises(InvalidTransitionError):
            sm.transition(ApprovalStatus.PENDING)  # self-loop

    def test_transition_from_terminal_raises(self):
        sm = ApprovalStateMachine()
        sm.transition(ApprovalStatus.APPROVED)
        with pytest.raises(InvalidTransitionError):
            sm.transition(ApprovalStatus.REJECTED)

    def test_escalated_cannot_re_escalate(self):
        sm = ApprovalStateMachine()
        sm.transition(ApprovalStatus.ESCALATED)
        with pytest.raises(InvalidTransitionError):
            sm.transition(ApprovalStatus.ESCALATED)

    def test_transition_with_reason(self):
        sm = ApprovalStateMachine()
        sm.transition(ApprovalStatus.APPROVED, reason="All checks passed")
        assert sm.history[-1] == (ApprovalStatus.APPROVED, "All checks passed")

    def test_history_tracks_all_transitions(self):
        sm = ApprovalStateMachine()
        sm.transition(ApprovalStatus.ESCALATED, reason="SLA exceeded")
        sm.transition(ApprovalStatus.APPROVED, reason="Manager override")
        assert len(sm.history) == 3
        assert sm.history[0] == (ApprovalStatus.PENDING, None)
        assert sm.history[1] == (ApprovalStatus.ESCALATED, "SLA exceeded")
        assert sm.history[2] == (ApprovalStatus.APPROVED, "Manager override")


class TestApprovalStateMachineCan:

    def test_can_approve_from_pending(self):
        sm = ApprovalStateMachine()
        assert sm.can(ApprovalStatus.APPROVED)

    def test_can_escalate_from_pending(self):
        sm = ApprovalStateMachine()
        assert sm.can(ApprovalStatus.ESCALATED)

    def test_cannot_transition_from_terminal(self):
        sm = ApprovalStateMachine()
        sm.approve()
        assert not sm.can(ApprovalStatus.REJECTED)


class TestApprovalStateMachineConvenienceMethods:

    def test_approve(self):
        sm = ApprovalStateMachine()
        sm.approve(reason="OK")
        assert sm.status == ApprovalStatus.APPROVED

    def test_reject(self):
        sm = ApprovalStateMachine()
        sm.reject(reason="Risk too high")
        assert sm.status == ApprovalStatus.REJECTED

    def test_escalate(self):
        sm = ApprovalStateMachine()
        sm.escalate(reason="Need manager review")
        assert sm.status == ApprovalStatus.ESCALATED

    def test_expire_from_pending(self):
        sm = ApprovalStateMachine()
        sm.expire(reason="SLA timeout")
        assert sm.status == ApprovalStatus.EXPIRED

    def test_expire_from_escalated(self):
        sm = ApprovalStateMachine()
        sm.escalate()
        sm.expire(reason="No response after escalation")
        assert sm.status == ApprovalStatus.EXPIRED

    def test_approve_from_escalated(self):
        sm = ApprovalStateMachine()
        sm.escalate()
        sm.approve(reason="Approved at level 2")
        assert sm.status == ApprovalStatus.APPROVED

    def test_repr(self):
        sm = ApprovalStateMachine()
        assert repr(sm) == "ApprovalStateMachine(status='pending')"


class TestInvalidTransitionError:

    def test_error_attributes(self):
        err = InvalidTransitionError(ApprovalStatus.APPROVED, ApprovalStatus.REJECTED)
        assert err.from_status == ApprovalStatus.APPROVED
        assert err.to_status == ApprovalStatus.REJECTED

    def test_error_message(self):
        err = InvalidTransitionError(ApprovalStatus.APPROVED, ApprovalStatus.REJECTED)
        assert "approved → rejected" in str(err)
