# tests/agents/test_phase2_search.py
"""Tests for Phase 2 self-reflective fix context retrieval (Agentic Search Step 3)."""

import pytest

from tools.quality.quality_evaluator import ReviewResult
from tools.rag import RAGConfig, RAGPipeline, Document
from tools.workflow.event_store import EventType, PipelineEventStore


def _make_docs() -> list[Document]:
    return [
        Document(content="Fix: JWT expiry not checked. Always validate 'exp' claim before trusting token.", source="fix_jwt.md"),
        Document(content="Fix: SQL injection in login. Use parameterized queries instead of string concat.", source="fix_sql.md"),
        Document(content="Fix: Missing input validation on email field. Add regex check before processing.", source="fix_validation.md"),
    ]


def _make_rag_pipeline() -> RAGPipeline:
    config = RAGConfig()
    p = RAGPipeline(config)
    p.ingest(_make_docs())
    return p


class TestSearchFixContext:
    """_search_fix_context: retrieve fix examples from RAGPipeline when issues exist."""

    def test_returns_context_when_issues_present(self):
        rag = _make_rag_pipeline()

        class FakePipeline:
            rag_pipeline = rag
            enable_memory = False

        fp = FakePipeline()
        # Bind the method from Phase2Pipeline
        from agents.pipeline_phase2 import Phase2Pipeline
        fp._search_fix_context = Phase2Pipeline._search_fix_context.__get__(fp, FakePipeline)

        issues = [{"severity": "critical", "message": "JWT expiry not validated"}]
        result = fp._search_fix_context(issues, module_name="authentication")

        assert "Retrieved fix context" in result
        assert len(result) > 0

    def test_returns_empty_when_no_rag_pipeline(self):
        class FakePipeline:
            rag_pipeline = None
            enable_memory = False

        from agents.pipeline_phase2 import Phase2Pipeline
        fp = FakePipeline()
        fp._search_fix_context = Phase2Pipeline._search_fix_context.__get__(fp, FakePipeline)

        result = fp._search_fix_context([{"message": "some issue"}])
        assert result == ""

    def test_returns_empty_when_no_issues(self):
        rag = _make_rag_pipeline()

        class FakePipeline:
            rag_pipeline = rag
            enable_memory = False

        from agents.pipeline_phase2 import Phase2Pipeline
        fp = FakePipeline()
        fp._search_fix_context = Phase2Pipeline._search_fix_context.__get__(fp, FakePipeline)

        result = fp._search_fix_context([])
        assert result == ""

    def test_query_includes_module_name(self):
        rag = _make_rag_pipeline()

        class FakePipeline:
            rag_pipeline = rag
            enable_memory = False

        from agents.pipeline_phase2 import Phase2Pipeline
        fp = FakePipeline()
        fp._search_fix_context = Phase2Pipeline._search_fix_context.__get__(fp, FakePipeline)

        issues = [{"message": "missing validation"}]
        result = fp._search_fix_context(issues, module_name="auth_module")
        assert "auth_module" in result or "Retrieved fix context" in result

    def test_top_k_limit_respected(self):
        rag = _make_rag_pipeline()

        class FakePipeline:
            rag_pipeline = rag
            enable_memory = False

        from agents.pipeline_phase2 import Phase2Pipeline
        fp = FakePipeline()
        fp._search_fix_context = Phase2Pipeline._search_fix_context.__get__(fp, FakePipeline)

        issues = [{"message": "JWT issue"}]
        result = fp._search_fix_context(issues)
        # At most 3 snippets (top_k=3 in _search_fix_context)
        snippet_count = result.count("- [")
        assert snippet_count <= 3


class TestEventStoreNewEventTypes:
    def test_search_context_retrieved_type_exists(self):
        assert EventType.SEARCH_CONTEXT_RETRIEVED.value == "search.context_retrieved"

    def test_fix_context_injected_type_exists(self):
        assert EventType.FIX_CONTEXT_INJECTED.value == "fix.context_injected"

    def test_new_events_in_event_store(self):
        store = PipelineEventStore(run_id="evt-test")
        store.append(EventType.PIPELINE_STARTED, {})
        store.append(EventType.QUALITY_GATE_FAILED, {"score": 0.55})
        store.append(EventType.SEARCH_CONTEXT_RETRIEVED, {"query": "fix: JWT", "hits": 2})
        store.append(EventType.FIX_CONTEXT_INJECTED, {"iteration": 0, "chars": 150})
        store.append(EventType.QUALITY_FIX_DONE, {})

        p = store.project()
        assert p["event_count"] == 5
        assert store.events[2].event_type == EventType.SEARCH_CONTEXT_RETRIEVED
        assert store.events[2].data["query"] == "fix: JWT"

    def test_persist_and_load_with_new_events(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            store = PipelineEventStore(run_id="persist-new-evt", base_dir=tmp)
            store.append(EventType.PIPELINE_STARTED, {})
            store.append(EventType.SEARCH_CONTEXT_RETRIEVED, {"query": "fix: test", "hits": 3})
            store.append(EventType.FIX_CONTEXT_INJECTED, {"iteration": 1})
            store.persist()

            restored = PipelineEventStore.load("persist-new-evt", base_dir=tmp)
            assert len(restored.events) == 3
            assert restored.events[1].event_type == EventType.SEARCH_CONTEXT_RETRIEVED
            assert restored.events[1].data["hits"] == 3


class TestFixContextsInjectionEndToEnd:
    """End-to-end: _fix_contexts collected in run_phase2 are passed through to build_pipeline_workflow."""

    def test_run_workflow_phase2_passes_fix_contexts_to_builder(self, monkeypatch):
        """_run_workflow_phase2 forwards fix_contexts to build_pipeline_workflow."""
        from unittest.mock import MagicMock
        from agents.pipeline_phase2 import Phase2Pipeline

        captured = {}

        def fake_build(compiled_pipeline, llm_provider=None,
                       tool_registry=None, agent_registry=None,
                       fix_contexts=None):
            captured["fix_contexts"] = fix_contexts
            workflow = MagicMock()
            workflow.id = "test-workflow"
            return workflow

        monkeypatch.setattr(
            "tools.workflow.build_pipeline_workflow",
            fake_build,
        )

        pipeline = MagicMock()
        pipeline.llm_provider = None
        pipeline.expert_agents = {}
        pipeline.enable_memory = False
        pipeline.workflow_engine = MagicMock()

        fix_ctxs = ["## Retrieved fix context\n- [fix_jwt.md] Fix: validate JWT"]
        Phase2Pipeline._run_workflow_phase2(
            pipeline, MagicMock(implementation_order=["auth"]), {},
            fix_contexts=fix_ctxs,
        )

        assert captured["fix_contexts"] is fix_ctxs

    def test_run_workflow_phase2_no_fix_contexts_by_default(self, monkeypatch):
        """When fix_contexts is None (default), build_pipeline_workflow receives None."""
        from unittest.mock import MagicMock
        from agents.pipeline_phase2 import Phase2Pipeline

        captured = {}

        def fake_build(compiled_pipeline, llm_provider=None,
                       tool_registry=None, agent_registry=None,
                       fix_contexts=None):
            captured["fix_contexts"] = fix_contexts
            workflow = MagicMock()
            workflow.id = "test-workflow"
            return workflow

        monkeypatch.setattr(
            "tools.workflow.build_pipeline_workflow",
            fake_build,
        )

        pipeline = MagicMock()
        pipeline.llm_provider = None
        pipeline.expert_agents = {}
        pipeline.enable_memory = False
        pipeline.workflow_engine = MagicMock()

        Phase2Pipeline._run_workflow_phase2(
            pipeline, MagicMock(implementation_order=["auth"]), {},
        )

        assert captured["fix_contexts"] is None
