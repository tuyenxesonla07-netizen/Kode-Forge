# tests/workflow/test_aggregator.py
"""Tests for ResultAggregator — sub-agent result aggregation."""

import pytest

from tools.workflow.engine import ResultAggregator, AgentResult


class TestResultAggregator:
    def test_add_single(self):
        agg = ResultAggregator()
        agg.add(AgentResult(agent_id="a1", module_name="auth",
                            components=["AuthService"], confidence=0.9))
        assert len(agg) == 1

    def test_merge_single_module(self):
        agg = ResultAggregator()
        agg.add(AgentResult(agent_id="a1", module_name="auth",
                            components=["AuthService"], confidence=0.9))
        merged = agg.merge()
        assert "auth" in merged
        assert merged["auth"].components == ["AuthService"]

    def test_merge_multi_agent_same_module(self):
        agg = ResultAggregator()
        agg.add(AgentResult(agent_id="a1", module_name="auth",
                            components=["AuthService"], confidence=0.7))
        agg.add(AgentResult(agent_id="a2", module_name="auth",
                            components=["AuthHelper"], confidence=0.9))
        merged = agg.merge()
        assert "auth" in merged
        assert set(merged["auth"].components) == {"AuthService", "AuthHelper"}
        assert merged["auth"].confidence == 0.9

    def test_detect_conflicts(self):
        agg = ResultAggregator()
        agg.add(AgentResult(agent_id="a1", module_name="auth",
                            interfaces=["get_user"]))
        agg.add(AgentResult(agent_id="a2", module_name="user",
                            interfaces=["get_user"]))
        conflicts = agg.detect_conflicts()
        assert len(conflicts) == 1
        assert conflicts[0]["interface"] == "get_user"

    def test_no_conflicts(self):
        agg = ResultAggregator()
        agg.add(AgentResult(agent_id="a1", module_name="auth",
                            interfaces=["authenticate"]))
        agg.add(AgentResult(agent_id="a2", module_name="cart",
                            interfaces=["add_item"]))
        conflicts = agg.detect_conflicts()
        assert len(conflicts) == 0

    def test_summary(self):
        agg = ResultAggregator()
        agg.add(AgentResult(agent_id="a1", module_name="auth",
                            status="success", confidence=0.9))
        agg.add(AgentResult(agent_id="a2", module_name="cart",
                            status="failed", confidence=0.3))
        summary = agg.get_summary()
        assert summary["total_agents"] == 2
        assert summary["success"] == 1
        assert summary["failed"] == 1
        assert summary["modules_covered"] == 2
