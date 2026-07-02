"""Tests for PipelineOrchestrator."""

import asyncio
import pytest
from tools.server.pipeline_orchestrator import PipelineOrchestrator, PipelineEvent


class TestPipelineEvent:
    def test_to_sse(self):
        event = PipelineEvent(
            tag="think",
            content="Testing",
            run_id="r1",
            node_id="n1",
        )
        sse = event.to_sse()
        assert "event: step" in sse
        assert '"tag": "think"' in sse
        assert '"content": "Testing"' in sse
        assert "run_id" in sse

    def test_default_timestamp(self):
        event = PipelineEvent(tag="think", content="test")
        assert event.timestamp != ""

    def test_custom_metadata(self):
        event = PipelineEvent(
            tag="node_complete",
            content="done",
            metadata={"duration_ms": 42},
        )
        sse = event.to_sse()
        assert "duration_ms" in sse


class TestPipelineOrchestrator:
    @pytest.mark.asyncio
    async def test_run_pipeline_basic(self):
        """Test basic pipeline execution with mock LLM."""
        from tools.llm.mock import MockLLMProvider

        provider = MockLLMProvider()
        orchestrator = PipelineOrchestrator(llm_provider=provider)
        result = await orchestrator.run_pipeline("构建用户登录模块")

        assert result is not None
        assert "status" in result
        assert "run_id" in result
        assert "elapsed_seconds" in result

    @pytest.mark.asyncio
    async def test_run_pipeline_returns_success(self):
        """Pipeline should complete successfully with mock LLM."""
        from tools.llm.mock import MockLLMProvider

        provider = MockLLMProvider()
        orchestrator = PipelineOrchestrator(llm_provider=provider)
        result = await orchestrator.run_pipeline("构建认证模块")

        assert result["status"] == "success"
        assert result["execution_time_ms"] >= 0

    @pytest.mark.asyncio
    async def test_stream_pipeline_yields_events(self):
        """Stream pipeline should yield PipelineEvent objects."""
        from tools.llm.mock import MockLLMProvider

        provider = MockLLMProvider()
        orchestrator = PipelineOrchestrator(llm_provider=provider)

        events = []
        async for event in orchestrator.stream_pipeline("构建认证模块"):
            events.append(event)

        # Should have at least think + complete events
        assert len(events) >= 2
        tags = [e.tag for e in events]
        assert "think" in tags
        assert "complete" in tags

    @pytest.mark.asyncio
    async def test_stream_pipeline_events_have_run_id(self):
        """All stream events should have a run_id."""
        from tools.llm.mock import MockLLMProvider

        provider = MockLLMProvider()
        orchestrator = PipelineOrchestrator(llm_provider=provider)

        events = []
        async for event in orchestrator.stream_pipeline("test requirement"):
            events.append(event)

        # All events should have a non-empty run_id
        for event in events:
            assert event.run_id != "", f"Event {event.tag} has empty run_id"

    @pytest.mark.asyncio
    async def test_fallback_on_compile_error(self):
        """Orchestrator should return a fallback workflow on compile error."""
        orchestrator = PipelineOrchestrator(llm_provider=None)
        # Monkey-patch to simulate compile failure
        orchestrator._compile_requirement = lambda req: None

        result = await orchestrator.run_pipeline("test")
        # Should return failed status, not crash
        assert result is not None
        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_stream_fallback_on_compile_error(self):
        """Stream should handle compile error gracefully."""
        orchestrator = PipelineOrchestrator(llm_provider=None)
        orchestrator._compile_requirement = lambda req: None

        events = []
        async for event in orchestrator.stream_pipeline("test"):
            events.append(event)

        # Should have error + complete events
        tags = [e.tag for e in events]
        assert "error" in tags
        assert "complete" in tags

    def test_engine_lazy_init(self):
        """Engine should be created lazily on first access."""
        orchestrator = PipelineOrchestrator()
        assert orchestrator._engine is None
        _ = orchestrator.engine
        assert orchestrator._engine is not None

    def test_create_progress_queue(self):
        """Progress queue should return queue + handlers."""
        orchestrator = PipelineOrchestrator()
        # Trigger engine + hooks init
        _ = orchestrator.engine
        q, handlers = orchestrator._create_progress_queue()
        assert q is not None
        assert len(handlers) == 4  # on_start, on_step, on_error, on_complete
