# tests/workflow/test_integration.py
"""Integration tests: Lifecycle + Recovery + Context + WorkflowEngine all together."""

import asyncio

import pytest

from tools.workflow.engine import (
    ContextWindow,
    WorkflowEngine,
    LifecycleHooks,
    RecoveryManager,
    RetryPolicy,
)


class TestIntegration:
    @pytest.mark.asyncio
    async def test_lifecycle_hooks_with_engine(self, tmp_path):
        hooks = LifecycleHooks()
        events = []
        hooks.register("on_start", lambda e: events.append("start"))
        hooks.register("on_complete", lambda e: events.append("complete"))
        hooks.emit("on_start", run_id="test_run")
        hooks.emit("on_complete", run_id="test_run")
        assert events == ["start", "complete"]

    def test_context_window_with_alerts(self):
        cw = ContextWindow(max_tokens=1000)
        cw.add_system("System prompt", priority=10)
        cw.add_tool_result("x" * 100, priority=1)
        prompt = cw.build()
        assert "System prompt" in prompt

    def test_recovery_with_retry_policy_customization(self):
        policy = RetryPolicy(
            max_retries=5, base_delay=0.5, max_delay=10.0,
            exponential=True, jitter=False,
        )
        assert policy.max_retries == 5
        assert policy.compute_delay(3) == 4.0

    @pytest.mark.asyncio
    async def test_engine_with_all_three_components(self, tmp_path):
        """Integration test: WorkflowEngine + ContextWindow + LifecycleHooks + RecoveryManager."""
        events = []
        hooks = LifecycleHooks()
        hooks.register("on_start", lambda e: events.append(("start", e.data.get("workflow_id", ""))))
        hooks.register("on_step", lambda e: events.append(("step", e.node_id)))
        hooks.register("on_complete", lambda e: events.append(("complete", e.data.get("status", ""))))
        hooks.register("on_error", lambda e: events.append(("error", e.node_id)))

        cw = ContextWindow(max_tokens=2000)
        cw.add_system("Test system prompt", priority=10)

        rm = RecoveryManager(
            policy=RetryPolicy(max_retries=1, base_delay=0.01, jitter=False),
        )

        engine = WorkflowEngine(
            checkpoint_dir=str(tmp_path),
            context_window=cw,
            lifecycle_hooks=hooks,
            recovery_manager=rm,
        )

        engine.load_workflow({
            "id": "wf-int",
            "name": "Integration Test",
            "nodes": [
                {"id": "n1", "type": "llm", "name": "Step1",
                 "config": {"prompt_template": "test"}},
            ],
            "edges": [],
        })

        run_id = await engine.execute_async("wf-int", {"input": "hello"})
        result = await engine.wait_for_run(run_id)

        assert result is not None
        assert result.status == "success"

        assert any(e[0] == "start" for e in events), "on_start not fired"
        assert any(e[0] == "step" for e in events), "on_step not fired"
        assert any(e[0] == "complete" for e in events), "on_complete not fired"

        prompt = cw.build()
        assert "Test system prompt" in prompt

    @pytest.mark.asyncio
    async def test_lifecycle_on_error_fires(self, tmp_path):
        """Verify on_error hook fires when a node fails."""
        events = []
        hooks = LifecycleHooks()
        hooks.register("on_error", lambda e: events.append(("error", e.data.get("error", ""))))
        hooks.register("on_complete", lambda e: events.append(("complete", e.data.get("status", ""))))

        engine = WorkflowEngine(
            checkpoint_dir=str(tmp_path),
            lifecycle_hooks=hooks,
            max_retries=0,
        )

        original_execute = engine._execute_node
        async def failing_execute(node, inputs, context=None):
            raise RuntimeError("Simulated node failure")
        engine._execute_node = failing_execute

        engine.load_workflow({
            "id": "wf-err",
            "name": "Error Test",
            "nodes": [
                {"id": "n1", "type": "llm", "name": "Failing",
                 "config": {"prompt_template": "test"}},
            ],
            "edges": [],
        })

        run_id = await engine.execute_async("wf-err", {"input": "test"})
        result = await engine.wait_for_run(run_id)

        assert result.status == "failed"
        error_events = [e for e in events if e[0] == "error"]
        assert len(error_events) >= 1, "on_error should fire on failure"
        assert "Simulated node failure" in error_events[0][1]

    @pytest.mark.asyncio
    async def test_context_window_trim_in_engine(self, tmp_path):
        """Verify ContextWindow trims when max_items exceeded during engine execution."""
        cw = ContextWindow(max_items=3)
        cw.add_system("System", priority=10)

        engine = WorkflowEngine(
            checkpoint_dir=str(tmp_path),
            context_window=cw,
        )

        engine.load_workflow({
            "id": "wf-ctx",
            "name": "Context Trim Test",
            "nodes": [
                {"id": "n1", "type": "llm", "name": "Step1",
                 "config": {"prompt_template": "test"}},
            ],
            "edges": [],
        })

        run_id = await engine.execute_async("wf-ctx", {"input": "test"})
        await engine.wait_for_run(run_id)

        assert len(cw) >= 1

    @pytest.mark.asyncio
    async def test_recovery_manager_degradation_in_engine(self, tmp_path):
        """Verify RecoveryManager triggers degradation when retries fail."""
        async def failing_execute():
            raise ConnectionError("always fails")

        rm = RecoveryManager(
            policy=RetryPolicy(max_retries=1, base_delay=0.01, jitter=False),
            degrade_fn=lambda ctx: "degraded_result",
        )

        result = await rm.execute_with_recovery(
            failing_execute,
            task_context={"node_id": "test"},
        )
        assert result.success is True
        assert result.strategy == "degrade"
        assert result.output == "degraded_result"

    @pytest.mark.asyncio
    async def test_backward_compat_no_components(self, tmp_path):
        """Verify engine works without any optional components (backward compat)."""
        engine = WorkflowEngine(checkpoint_dir=str(tmp_path))
        engine.load_workflow({
            "id": "wf-basic",
            "name": "Basic",
            "nodes": [
                {"id": "n1", "type": "llm", "name": "Step",
                 "config": {"prompt_template": "test"}},
            ],
            "edges": [],
        })
        run_id = await engine.execute_async("wf-basic", {"input": "test"})
        result = await engine.wait_for_run(run_id)
        assert result.status == "success"

    def test_engine_component_accessors(self):
        """Verify components are accessible via attributes."""
        cw = ContextWindow()
        hooks = LifecycleHooks()
        rm = RecoveryManager()
        engine = WorkflowEngine(
            context_window=cw,
            lifecycle_hooks=hooks,
            recovery_manager=rm,
        )
        assert engine.context_window is cw
        assert engine.lifecycle_hooks is hooks
        assert engine.recovery_manager is rm

    def test_engine_default_components(self):
        """Verify engine creates default LifecycleHooks when none provided."""
        engine = WorkflowEngine()
        assert engine.lifecycle_hooks is not None
        assert isinstance(engine.lifecycle_hooks, LifecycleHooks)
        assert engine.context_window is None
        assert engine.recovery_manager is None
