# tests/workflow/test_human_node.py
"""Tests for HumanNode — HITL approval node in workflow."""

import asyncio

import pytest

from tools.workflow.nodes import HumanNode


class TestHumanNode:
    @pytest.fixture
    def auto_handler(self):
        from tools.hitl.approval import AutoApprovalHandler
        return AutoApprovalHandler(auto_under_risk="medium")

    @pytest.fixture
    def manual_handler(self):
        from tools.hitl.approval import ManualApprovalHandler
        return ManualApprovalHandler()

    @pytest.mark.asyncio
    async def test_human_node_with_auto_handler_approved(self, auto_handler):
        node = HumanNode(prompt="确认删除？", risk_level="low",
                         approval_handler=auto_handler)
        result = await node.execute({"user_id": "U123"})
        assert result["approved"] is True
        assert result["approver"] == "auto"

    @pytest.mark.asyncio
    async def test_human_node_with_auto_handler_requires_human(self, auto_handler):
        node = HumanNode(prompt="确认删除？", risk_level="high",
                         approval_handler=auto_handler)
        result = await node.execute({"user_id": "U123"})
        assert result["approved"] is False
        assert result["requires_human"] is True

    @pytest.mark.asyncio
    async def test_human_node_with_manual_handler(self, manual_handler):
        node = HumanNode(prompt="确认退款？", risk_level="high",
                         approval_handler=manual_handler)
        result = await node.execute({"order_id": "O456"})
        assert result["approved"] is False
        assert result["requires_human"] is True

    @pytest.mark.asyncio
    async def test_human_node_no_handler(self):
        node = HumanNode(prompt="确认操作？", risk_level="high")
        result = await node.execute({})
        assert result["approved"] is True  # degraded mode
        assert result["approver"] == "none"

    @pytest.mark.asyncio
    async def test_human_node_returns_prompt(self, auto_handler):
        node = HumanNode(prompt="确认删除用户数据？", risk_level="low",
                         approval_handler=auto_handler)
        result = await node.execute({})
        assert result["prompt"] == "确认删除用户数据？"
