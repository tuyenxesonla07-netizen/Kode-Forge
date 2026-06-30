# tests/langgraph_adapter/test_human_interrupt.py

"""
Tests for tools.langgraph_adapter.human_interrupt — interrupt/resume helpers.

纯 Python 测试，无 LangGraph 依赖。
"""

import pytest

from tools.langgraph_adapter.human_interrupt import (
    make_human_interrupt_node,
    resume_with_approval,
    check_pending_human,
    is_human_approval_needed,
)
from tools.langgraph_adapter.state import initial_state


class TestResumeWithApproval:

    def test_approved(self):
        data = resume_with_approval(True, "LGTM")
        assert data["pending_human"]["approved"] is True
        assert data["pending_human"]["reason"] == "LGTM"

    def test_rejected(self):
        data = resume_with_approval(False, "Risk too high")
        assert data["pending_human"]["approved"] is False
        assert data["pending_human"]["reason"] == "Risk too high"

    def test_default_reason(self):
        data = resume_with_approval(True)
        assert data["pending_human"]["reason"] == ""


class TestCheckPendingHuman:

    def test_no_pending(self):
        state = initial_state()
        assert check_pending_human(state) is None

    def test_pending_with_no_decision(self):
        state = initial_state(pending_human={
            "node_id": "deploy",
            "prompt": "确认？",
            "approved": None,
        })
        result = check_pending_human(state)
        assert result is not None
        assert result["node_id"] == "deploy"

    def test_pending_already_approved(self):
        state = initial_state(pending_human={
            "node_id": "deploy",
            "approved": True,
            "reason": "OK",
        })
        assert check_pending_human(state) is None

    def test_pending_already_rejected(self):
        state = initial_state(pending_human={
            "node_id": "deploy",
            "approved": False,
            "reason": "nope",
        })
        assert check_pending_human(state) is None


class TestIsHumanApprovalNeeded:

    def test_not_needed_no_pending(self):
        state = initial_state()
        assert is_human_approval_needed(state) is False

    def test_needed_when_pending(self):
        state = initial_state(pending_human={
            "node_id": "deploy",
            "approved": None,
        })
        assert is_human_approval_needed(state) is True

    def test_not_needed_when_resolved(self):
        state = initial_state(pending_human={
            "node_id": "deploy",
            "approved": True,
        })
        assert is_human_approval_needed(state) is False


class TestMakeHumanInterruptNode:

    @pytest.mark.asyncio
    async def test_first_call_sets_pending(self):
        async def dummy_fn(state):
            return {"result": "done"}

        wrapped = make_human_interrupt_node(dummy_fn, prompt="确认部署？", risk_level="high")
        state = initial_state()
        result = await wrapped(state)
        assert result["pending_human"]["prompt"] == "确认部署？"
        assert result["pending_human"]["risk_level"] == "high"
        assert result["pending_human"]["approved"] is None

    @pytest.mark.asyncio
    async def test_approved_resumes(self):
        async def dummy_fn(state):
            return {"output": "executed"}

        wrapped = make_human_interrupt_node(dummy_fn, prompt="Confirm?")
        state = initial_state(pending_human={
            "node_id": "deploy",
            "approved": True,
            "reason": "OK",
        })
        result = await wrapped(state)
        assert result["output"] == "executed"
        assert result["pending_human"] is None

    @pytest.mark.asyncio
    async def test_rejected_returns_error(self):
        async def dummy_fn(state):
            return {"output": "executed"}

        wrapped = make_human_interrupt_node(dummy_fn, prompt="Confirm?")
        state = initial_state(pending_human={
            "node_id": "deploy",
            "approved": False,
            "reason": "Risk too high",
        })
        result = await wrapped(state)
        assert "Rejected by human" in result["errors"][0]
        assert result["pending_human"] is None

    def test_wrapped_fn_name(self):
        async def my_node(state):
            return {}
        wrapped = make_human_interrupt_node(my_node)
        assert "human_interrupt" in wrapped.__name__
