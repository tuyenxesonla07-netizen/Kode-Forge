# tests/workflow/test_enhancements_integration.py
"""Integration tests: HumanNode in WorkflowEngine + StrictMode output guard."""

import asyncio

import pytest

from tools.workflow.engine import WorkflowEngine


class TestHumanNodeInEngine:
    @pytest.mark.asyncio
    async def test_workflow_with_human_node(self):
        engine = WorkflowEngine()
        from tools.hitl.approval import AutoApprovalHandler

        handler = AutoApprovalHandler(auto_under_risk="high")

        workflow = engine.load_workflow({
            "id": "wf-hitl",
            "name": "HITL Test",
            "nodes": [
                {"id": "n1", "type": "llm", "name": "Analysis",
                 "config": {"prompt_template": "Analyze: {{input}}"}},
                {"id": "n2", "type": "human", "name": "Approval",
                 "config": {"prompt": "确认执行？", "risk_level": "high"},
                 "inputs": ["n1"]},
            ],
            "edges": [{"from": "n1", "to": "n2"}],
        })

        run_id = await engine.execute_async("wf-hitl", {"input": "test"},
                                              context={"approval_handler": handler})
        result = engine.get_run_result(run_id)

        await asyncio.sleep(0.1)
        result = engine.get_run_result(run_id)

        assert "n2" in result.outputs
        assert result.outputs["n2"]["approved"] is True


class TestStrictMode:
    def test_strict_mode_blocks_overpromise(self):
        from tools.guardrails import OutputGuard
        guard = OutputGuard(strict=True)
        result = guard.check("我们保证100%退款")
        assert result.passed is False
        assert "严格模式" in result.issues[0]

    def test_non_strict_rewrites_overpromise(self):
        from tools.guardrails import OutputGuard
        guard = OutputGuard(strict=False)
        result = guard.check("我们保证100%退款")
        assert result.passed is True
        assert "按政策为您申请退款" in result.text
